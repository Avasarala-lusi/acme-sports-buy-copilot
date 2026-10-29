"""Buy-plan engine: weekly visibility, configured MID/EOM purchases.

Every weekly MRP run takes in new demand (Rule 5 is applied on arrival). Purchases are committed
only in configured buying runs (exact cutoff-to-PO mapping remains provisional). The other
runs show a draft of what the next window would buy with what is known now; a draft changes nothing.

Demand that is not yet due is carried forward (rolling window), and the capacity ledger accumulates
our own committed assignments. Factory loads are checked with the new lot included, and a lot that
fits no certified factory goes to planner review instead of being bought. Every requisition ends
with exactly one outcome.
"""
from dataclasses import dataclass, field
import hashlib
from threading import RLock

import pandas as pd

from engine.calendar import BuyingCalendar, window_label
from engine.capacity import CapacityLedger
from engine.config import load_config
from engine.data_loader import AcmeData, load_data
from engine.rules import exclusion, timing
from engine.rules.assignment import REVIEW, STATUS_LABELS, choose_from_chain
from engine.rules.grouping import group_by_rdd
from engine.rules.quantities import OK, PIGGYBACK, mpq_for, pick_to_fill, quantity_status

BOUGHT = "BOUGHT"
FUTURE_FORECAST = "FUTURE_FORECAST"
UNRESOLVED_MOQ = "UNRESOLVED_MOQ"
UNRESOLVED_MPQ = "UNRESOLVED_MPQ"
PLANNER_REVIEW = "PLANNER_REVIEW"
OPEN = "OPEN"
TERMINAL = {BOUGHT, FUTURE_FORECAST, UNRESOLVED_MOQ, UNRESOLVED_MPQ, PLANNER_REVIEW}
COMMITTED, DRAFT = "Committed", "Draft"


@dataclass
class Lot:
    lot_id: str
    run_id: str
    article_id: str
    market: str
    pr_ids: list[str]
    last_chance: bool = False
    piggyback_sources: list[str] = field(default_factory=list)
    piggyback_prs: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    factory: str | None = None
    routed_to_backup: bool = False
    decision_type: str = "auto"


@dataclass
class RunResult:
    run_id: str
    lots: pd.DataFrame
    outcomes: pd.DataFrame
    open_prs: list[str]
    is_buying_run: bool = True
    open_reasons: dict = field(default_factory=dict)
    buy_date: pd.Timestamp | None = None      # PO date of the window this run commits or previews
    next_buy_date: pd.Timestamp | None = None

    @property
    def plan_status(self) -> str:
        return COMMITTED if self.is_buying_run else DRAFT


class Planner:
    def __init__(self, data: AcmeData | None = None, config: dict | None = None, decisions: dict | None = None):
        self.cfg = config or load_config()
        self._plan_lock = RLock()
        self.decisions = decisions or {}
        self.calendar = BuyingCalendar.from_config(self.cfg)
        self.data = data or load_data()
        self._prepare()
        self.reset()

    # ---------------------------------------------------------------- setup
    def _prepare(self) -> None:
        d, cfg = self.data, self.cfg
        art = d.articles.set_index("article_id")
        fac = d.factories.set_index("factory_id")
        self.factories = fac
        self.certified = (d.cert_matrix[d.cert_matrix["is_certified"]]
                          .groupby("article_id")["factory_id"].apply(set).to_dict())

        so = d.sales_orders.set_index("pr_id")
        prs = d.prs.copy()
        prs["category"] = prs["article_id"].map(art["category"])
        prs["unit_cost_usd"] = prs["article_id"].map(art["unit_cost_usd"])
        prs["early_buy"] = prs["article_id"].map(art["early_buy_flag"]).astype(bool)
        prs["last_chance"] = prs["article_id"].map(art["last_chance_flag"]).astype(bool)
        prs["primary"] = prs["article_id"].map(art["primary_factory"])
        # backup chains: article-level (one backup per article) or the factory-level chain, walked
        # backup -> backup's backup -> ... to the last resort (data v5: acyclic, ending at CN04)
        factory_backup = fac["backup_factory"].dropna().to_dict()

        def walk(f):
            out = []
            while f in factory_backup and factory_backup[f] not in out and factory_backup[f] != f:
                f = factory_backup[f]
                out.append(f)
            return out

        source = cfg["backup_source"]
        if source == "article":
            self.backup_chain = {a: [b] for a, b in art["backup_factory"].dropna().items()}
            prs["backup"] = prs["article_id"].map(art["backup_factory"])
        elif source in ("factory", "factory_chain"):
            chains = {f: walk(f) for f in fac.index}
            if source == "factory":
                chains = {f: c[:1] for f, c in chains.items()}
            self.backup_chain = {a: chains[p] for a, p in art["primary_factory"].items()}
            prs["backup"] = prs["article_id"].map(lambda a: (self.backup_chain.get(a) or [None])[0])
        else:
            raise ValueError(f"unknown backup_source {source}")
        prs["has_order"] = prs["pr_id"].isin(so.index)
        prs["nsv"] = prs["pr_id"].map(so["net_sales_value"]).fillna(0.0)
        # data v5 carries the customer on every requisition; earlier versions only on sales orders
        cust = prs["customer_id"] if "customer_id" in prs else prs["pr_id"].map(so["customer_id"])
        if cfg["data"]["dtc_as_single_customer"]:
            cust = cust.where(prs["channel_id"] != exclusion.DTC, "DTC")
        prs["customer_id"] = cust
        mid_mfg = (fac["mfg_lt_min_days"] + fac["mfg_lt_max_days"]) / 2
        mid_trn = (fac["trans_lt_min_days"] + fac["trans_lt_max_days"]) / 2
        same = prs["primary"] == prs["assigned_factory"]
        mfg = prs["manufacturing_lead_time"].where(same, prs["primary"].map(mid_mfg))
        trn = prs["transportation_lead_time"].where(same, prs["primary"].map(mid_trn))
        prs["release_primary"] = prs["rdd_original"] - pd.to_timedelta(mfg + trn, unit="D")
        self.prs = prs.set_index("pr_id", drop=False)
        self.rows: dict[str, dict] = self.prs.to_dict("index")
        self.mid_lt = {f: ((r["mfg_lt_min_days"] + r["mfg_lt_max_days"]) / 2,
                           (r["trans_lt_min_days"] + r["trans_lt_max_days"]) / 2)
                       for f, r in fac.iterrows()}

        runs = d.runs.sort_values("week_number").reset_index(drop=True)
        self.runs = runs
        self.run_index = {r: i for i, r in enumerate(runs["run_id"])}
        self.prs["run_num"] = self.prs["run_id"].map(self.run_index)
        self.new_by_run = self.prs.groupby("run_id")["pr_id"].apply(list).to_dict()
        self.window_run = {pd.Timestamp(r.po_execution_date).normalize(): r.run_id
                           for r in runs.itertuples() if self.calendar.is_window(r.po_execution_date)}

    def reset(self) -> None:
        cap = self.factories["weekly_capacity_units"].to_dict()
        self.ledger = CapacityLedger(cap, self.cfg["capacity"]["spread_over_manufacturing"])
        self.open: dict[str, str] = {}          # pr_id -> latest wait reason
        self.pr_notes: dict[str, list[str]] = {}  # Rule 5 exceptions recorded on arrival
        self.outcomes: dict[str, dict] = {}
        self.results: dict[str, RunResult] = {}
        self.lot_rows: list[dict] = []
        self.snapshots: dict[str, CapacityLedger] = {}
        self.decision_issues = []
        self.processed = -1

    # ---------------------------------------------------------------- helpers
    def lead_times(self, pr, factory: str) -> tuple[int, int]:
        """Lead times for a requisition (row dict or Series) at a factory."""
        if factory == pr["assigned_factory"]:
            return int(pr["manufacturing_lead_time"]), int(pr["transportation_lead_time"])
        return self.mid_lt[factory]

    def lot_lead_times(self, pr_ids: list[str], factory: str) -> tuple[int, int]:
        lts = [self.lead_times(self.rows[p], factory) for p in pr_ids]
        return max(m for m, _ in lts), max(t for _, t in lts)

    def release_at(self, pr_id: str, factory: str) -> pd.Timestamp:
        pr = self.rows[pr_id]
        if factory == pr["primary"]:
            return pr["release_primary"]
        m, t = self.lead_times(pr, factory)
        return timing.release_date(pr["rdd_original"], m, t)

    def _qty(self, pr_ids) -> float:
        return float(sum(self.rows[p]["requested_qty"] for p in pr_ids))

    def _min_rdd(self, pr_ids) -> pd.Timestamp:
        return min(self.rows[p]["rdd_original"] for p in pr_ids)

    def priority_key(self, ids):
        """Allocation order when capacity is short. Client (Oct 29): last chance, then earliest release date; ties on
        the release date go to the earliest RDD, then the highest net sales value, then order-backed demand.
        Category/factory MPQ remains a separate feasibility gate."""
        def key(pr_id):
            pr=self.rows[pr_id]
            tie=(pr["rdd_original"],-pr["nsv"],-int(pr["has_order"]))
            if self.cfg.get("priority",{}).get("tie_break")=="revenue_then_rdd":  # earlier reading, kept as an option
                tie=(-int(pr["has_order"]),-pr["nsv"],pr["rdd_original"])
            return (-int(pr["last_chance"]),pr["release_primary"],*tie,pr_id)
        return min(key(p) for p in ids)  # consolidated lot inherits its highest-priority PR

    def rdd_span_ok(self, ids):
        dates = [self.rows[p]["rdd_original"] for p in ids]
        return bool(dates) and (max(dates) - min(dates)).days <= self.cfg["grouping"]["window_days"]

    def eligible_pull(self, p, buy_date):
        original = self.calendar.on_or_before(self.rows[p]["release_primary"])
        target = pd.Timestamp(buy_date).normalize()
        if (target not in self.window_run or pd.Timestamp(original) not in self.window_run
                or self.run_index[self.rows[p]["run_id"]] > self.processed + 1):
            return False
        cursor, count = target.date(), 0
        while cursor < original:
            cursor = self.calendar.after(cursor)
            count += 1
        return cursor <= original and count <= self.cfg["buying_window"].get("max_pull_forward_windows", 4)

    def mpq_groups(self, lots):
        """Same article/factory and anchored 15-day span, across market lots."""
        groups = {}
        for lot in sorted(lots, key=lambda x: x["earliest_rdd"]):
            key = (lot["article_id"], lot["assigned_factory"])
            bands = groups.setdefault(key, [])
            ids = lot["pr_ids"].split(",")
            if bands and self.rdd_span_ok([p for x in bands[-1] for p in x["pr_ids"].split(",")] + ids):
                bands[-1].append(lot)
            else:
                bands.append([lot])
        return [band for bands in groups.values() for band in bands]

    def _retried(self, pr_id: str) -> bool:
        """The requisition was sent to planner review or left unresolved in an earlier window."""
        return self.outcomes.get(pr_id, {}).get("outcome") in {PLANNER_REVIEW, UNRESOLVED_MOQ, UNRESOLVED_MPQ}

    def _decide(self, pr_ids, run_id: str, outcome: str, reason: str, lot_id: str | None = None):
        for p in pr_ids:
            self.outcomes[p] = {"pr_id": p, "decided_in_run": run_id, "outcome": outcome,
                                "lot_id": lot_id, "reason": reason}
            if outcome in {PLANNER_REVIEW, UNRESOLVED_MOQ, UNRESOLVED_MPQ}:
                self.open[p] = reason
            else:
                self.open.pop(p, None)

    # ---------------------------------------------------------------- main loop
    def __getstate__(self):
        state=self.__dict__.copy()
        for key in ("_plan_lock","_decision_replay","automatic_reference"):
            state.pop(key,None)
        return state

    def __setstate__(self,state):
        self.__dict__.update(state)
        self._plan_lock=RLock()

    def plan_through(self, run_id: str) -> None:
        # API pages can request plan/capacity/trend concurrently on the same replay.
        with self._plan_lock:
            target = self.run_index[run_id]
            while self.processed < target:
                self._process(self.processed + 1)

    def plan_all(self) -> None:
        self.plan_through(self.runs["run_id"].iloc[-1])

    def _process(self, k: int) -> None:
        run = self.runs.iloc[k]
        run_id = run["run_id"]
        po_date = pd.Timestamp(run["po_execution_date"]).normalize()
        buy_date = pd.Timestamp(self.calendar.on_or_after(po_date))
        next_buy = pd.Timestamp(self.calendar.after(buy_date))
        is_buying = buy_date == po_date
        decided_before = dict(self.outcomes)

        self._intake(run_id)
        if is_buying:
            rows, ledger = self._cascade(run_id, buy_date, next_buy, draft=False)
            if self.decisions.get(run_id):
                from engine.overrides import apply_run_decisions
                rows, ledger = apply_run_decisions(self, run_id, rows, buy_date, self.decisions[run_id])
            self.ledger = ledger
            self.lot_rows.extend(rows)
            decided_now = [o for p, o in self.outcomes.items() if o != decided_before.get(p)]
            open_now = dict(self.open)
        else:
            # Draft: preview the next window with what is known now, then restore the state.
            saved_open, saved_outcomes = dict(self.open), dict(self.outcomes)
            if self.cfg["buying_window"].get("weekly_drafts", True):
                rows, ledger = self._cascade(run_id, buy_date, next_buy, draft=True)
            else:
                rows, ledger = [], self.ledger.copy()
            decided_now = [o for p, o in self.outcomes.items() if o != decided_before.get(p)]
            open_now = dict(self.open)
            self.open, self.outcomes = saved_open, saved_outcomes
            # Rule 5 decisions taken on arrival are real, not part of the draft
            for o in decided_now:
                if o["outcome"] == FUTURE_FORECAST:
                    self.outcomes[o["pr_id"]] = o
                    self.open.pop(o["pr_id"], None)

        self.results[run_id] = RunResult(run_id, pd.DataFrame(rows), pd.DataFrame(decided_now), list(open_now),
                                         is_buying, open_now, buy_date, next_buy)
        self.snapshots[run_id] = ledger.copy()
        self.processed = k

    def _intake(self, run_id: str) -> None:
        """Rule 5 on new demand, as it arrives."""
        lc_forecast = self.cfg["last_chance"]["include_forecast_only"]
        for p in self.new_by_run.get(run_id, []):
            pr = self.rows[p]
            excluded = exclusion.forecast_excluded(pr["channel_id"], pr["has_order"], pr["early_buy"])
            if excluded and pr["last_chance"] and not lc_forecast:
                self._decide([p], run_id, PLANNER_REVIEW, "Last-chance versus unconfirmed wholesale: planner review")
                continue
            if excluded and not (pr["last_chance"] and lc_forecast):
                self._decide([p], run_id, FUTURE_FORECAST, exclusion.EXCLUSION_REASON)
                continue
            self.open[p] = "New this week"
            if pr["channel_id"] == exclusion.WHOLESALE and not pr["has_order"]:
                self.pr_notes[p] = [exclusion.EARLY_BUY_REASON if pr["early_buy"] else exclusion.LAST_CHANCE_REASON]

    def _cascade(self, run_id: str, buy_date: pd.Timestamp, next_buy: pd.Timestamp, draft: bool):
        """Rules 6, 1, 2, 3, 4 and capacity routing on the open pool, for the window at buy_date."""
        cfg = self.cfg
        moq = cfg["quantities"]["moq_per_market"]
        tol = cfg["piggyback"]["tolerance_pct"]

        # --- Rule 6 / Rule 1 on the whole open pool
        notes: dict[str, list[str]] = {p: list(self.pr_notes.get(p, [])) for p in self.open}
        due, waiting = [], []
        pool = self.prs.loc[list(self.open), ["pr_id", "release_primary", "last_chance"]]
        forced = {p: move for move in self.decisions.get(run_id,{}).get("pulls",[]) for p in move["pr_ids"]}
        for p, rel, last_chance in pool.itertuples(index=False):
            if exclusion.forecast_excluded(self.rows[p]["channel_id"], self.rows[p]["has_order"], self.rows[p]["early_buy"]):
                continue  # conflict remains visible, never quietly promoted to a purchase
            if p in forced and self.eligible_pull(p,buy_date):
                due.append(p)
                notes[p].append("Capacity pull-forward accepted by planner")
            elif (not last_chance and pd.Timestamp(rel) < buy_date and self._retried(p)
                  and cfg["capacity"].get("retried_late_demand", "planner_review") == "planner_review"):
                # Demand already sent to review/unresolved is retried for visibility, but once its release date has
                # passed it can only arrive late: the planner decides instead of an automatic late purchase.
                days = (buy_date - pd.Timestamp(rel)).days
                self._decide([p], run_id, PLANNER_REVIEW,
                             f"Retried demand: production could start only {days} days after its release date, "
                             "so it would arrive late; planner decision")
            elif last_chance:
                due.append(p)
                notes[p].append(exclusion.LAST_CHANCE_REASON)
            elif timing.is_due(rel, next_buy):
                due.append(p)
                notes[p].append(timing.due_reason(rel, buy_date, next_buy))
            else:
                waiting.append(p)
                self.open[p] = timing.wait_reason(rel, next_buy)

        # future pool for piggyback, earliest RDD first
        future = (self.prs.loc[waiting].sort_values("rdd_original")
                  if waiting else self.prs.iloc[0:0])
        used_future: set[str] = set()

        def candidates(article, markets=None, base_ids=None):
            f = future[(future["article_id"] == article) & ~future["pr_id"].isin(used_future)]
            if markets is not None:
                f = f[f["market_destination"].isin(markets)]
            f = f.loc[f["pr_id"].map(lambda p: self.eligible_pull(p, buy_date)).astype(bool)]
            if base_ids:
                f = f.loc[f["pr_id"].map(lambda p: self.rdd_span_ok(base_ids + [p])).astype(bool)]
            return f

        # --- Rule 2: group due demand by article + market
        lots: list[Lot] = []
        due_df = self.prs.loc[due] if due else self.prs.iloc[0:0]
        for (article, market), g in due_df.groupby(["article_id", "market_destination"]):
            ids = list(g["pr_id"])
            for pos in group_by_rdd(list(g["rdd_original"]), cfg["grouping"]["window_days"],
                                    cfg["grouping"]["mode"]):
                lot_prs = [ids[i] for i in pos]
                lot = Lot(lot_id="", run_id=run_id, article_id=article, market=market,
                          pr_ids=lot_prs, last_chance=bool(g["last_chance"].iloc[0]))
                moves = [forced[p] for p in lot_prs if p in forced]
                if moves:
                    lot.factory=moves[0]["factory"]
                    lot.decision_type="manual"
                    lot.piggyback_sources=sorted({m["source_run_id"] for m in moves})
                    lot.reasons.append("Capacity pull-forward: planner accepted; not a 5% quantity top-up")
                lot.reasons.append(f"Rule 2: {len(lot_prs)} requisition(s) grouped, RDDs within "
                                   f"{cfg['grouping']['window_days']} days")
                lots.append(lot)

        # --- Rule 3 MOQ (+ Rule 4 piggyback)
        kept = []
        for lot in lots:
            qty = self._qty(lot.pr_ids)
            status = quantity_status(qty, moq, tol)
            if status == PIGGYBACK:
                c = candidates(lot.article_id, [lot.market], lot.pr_ids)
                picked = pick_to_fill(moq - qty, list(zip(c["pr_id"], c["requested_qty"])))
                if picked and self.rdd_span_ok(lot.pr_ids + picked):
                    self._apply_piggyback(lot, picked, used_future,
                                          f"Rule 4: {qty:.0f} was within {tol}% of MOQ {moq}")
                    status = OK
            if status == OK:
                lot.reasons.append(f"Rule 3: lot of {self._qty(lot.pr_ids):.0f} meets MOQ {moq}")
                kept.append(lot)
            elif lot.last_chance:
                lot.warnings.append(f"Below MOQ: {qty:.0f} < {moq}, bought anyway (last chance)")
                kept.append(lot)
            elif self._can_wait(lot.pr_ids, next_buy):
                for p in lot.pr_ids:
                    self.open[p] = f"Rule 3: lot of {qty:.0f} below MOQ {moq}; waiting for more demand"
            else:
                self._decide(lot.pr_ids, run_id, UNRESOLVED_MOQ,
                             f"Rule 3: lot of {qty:.0f} below MOQ {moq} and cannot wait for the next window")

        # --- capacity routing + Rule 3 MPQ (+ Rule 4), repeated until stable
        lots = kept
        for _ in range(6):
            ledger, placed = self._assign(lots, buy_date)
            changed, lots = self._check_mpq(placed, lots, candidates, used_future, run_id, next_buy, tol)
            if not changed:
                break
        else:
            ledger, placed = self._assign(lots, buy_date)

        # Routing can change factory/date groups between cascade iterations. A final
        # minimum gate must inspect the actual final assignment, never an earlier pass.
        candidates_final=[dict(article_id=l.article_id,assigned_factory=placed[id(l)]["factory"],
            earliest_rdd=self._min_rdd(l.pr_ids),pr_ids=",".join(l.pr_ids),
            consolidated_qty=self._qty(l.pr_ids),category=self.rows[l.pr_ids[0]]["category"],
            last_chance=l.last_chance,object_id=id(l)) for l in lots if placed[id(l)]["status"]!=REVIEW]
        for band in self.mpq_groups(candidates_final):
            minimum=mpq_for(band[0]["category"],cfg["quantities"]["mpq"])
            if sum(r["consolidated_qty"] for r in band)<minimum and not any(r["last_chance"] for r in band):
                for r in band:
                    a=placed[r["object_id"]]
                    ledger.remove(a["factory"],a["start"],a["mfg"],a["qty"])
                    a["status"]=REVIEW
                    a["warnings"].append("Final article/factory/15-day group is below MPQ; planner review")

        # --- record lots: bought, or sent to planner review
        rows = []
        prefix = "D" if draft else "L"
        for n, lot in enumerate(sorted(lots, key=lambda l: self._min_rdd(l.pr_ids)), 1):
            identity = hashlib.sha256(",".join(sorted(lot.pr_ids)).encode()).hexdigest()[:12]
            lot.lot_id = f"{run_id}-{prefix}{identity}"
            row = self._lot_row(lot, placed[id(lot)], notes, buy_date, draft)
            rows.append(row)
            if row["auto_decision"] == "Buy":
                self._decide(lot.pr_ids, run_id, BOUGHT, "; ".join(lot.reasons), lot.lot_id)
            else:
                self._decide(lot.pr_ids, run_id, PLANNER_REVIEW,
                             row["warnings"] or "Needs planner review", lot.lot_id)

        for p in used_future:  # piggybacked demand left the open pool
            if self.outcomes.get(p, {}).get("outcome") == BOUGHT:
                self.open.pop(p, None)
        return rows, ledger

    # ---------------------------------------------------------------- steps
    def _apply_piggyback(self, lot: Lot, picked, used_future, why: str) -> None:
        lot.pr_ids.extend(picked)
        lot.piggyback_prs.extend(picked)
        used_future.update(picked)
        sources = sorted({self.window_run[pd.Timestamp(self.calendar.on_or_before(
            self.release_at(p, self.rows[p]["primary"]))) ] for p in picked})
        lot.piggyback_sources.extend(s for s in sources if s not in lot.piggyback_sources)
        lot.reasons.append(f"{why}; pulled {self._qty(picked):.0f} units forward from {', '.join(sources)}")

    def _can_wait(self, pr_ids, next_buy) -> bool:
        if not self.cfg["carry_forward"]["wait_if_not_late"]:
            return False
        return all(self.rows[p]["release_primary"] >= next_buy for p in pr_ids)

    def _assign(self, lots: list[Lot], po_date):
        cfg = self.cfg["capacity"]
        ledger = self.ledger.copy()
        placed = {}
        order = sorted(lots, key=lambda l: self.priority_key(l.pr_ids))
        for lot in order:
            first = self.rows[lot.pr_ids[0]]
            primary = first["primary"]
            certified = self.certified[lot.article_id]
            rdd = self._min_rdd(lot.pr_ids)
            qty = self._qty(lot.pr_ids)

            chain = self.backup_chain.get(lot.article_id, [])
            options = {}
            for f in dict.fromkeys([primary, *chain]):
                if f not in certified:
                    continue
                m, t = self.lot_lead_times(lot.pr_ids, f)
                release = rdd - pd.Timedelta(days=m + t)
                start = pd.Timestamp(po_date)
                weeks = ledger.weeks_for(start, m)
                options[f] = {"mfg": m, "trans": t, "release": release, "start": start,
                              "before": ledger.utilization(f, weeks),
                              "after": ledger.utilization_with(f, start, m, qty)}
            a = choose_from_chain(primary, chain, certified, {f: o["after"] for f, o in options.items()},
                                  cfg["backup_threshold_pct"], cfg["hard_limit_pct"], lot.last_chance,
                                  cfg["when_no_capacity"])
            if lot.factory:
                from engine.rules.assignment import Assignment
                if lot.factory not in options:
                    raise ValueError("Accepted pull-forward target is not certified")
                a = Assignment(lot.factory, routed_to_backup=lot.factory!=primary)
                if options[lot.factory]["after"] >= cfg["backup_threshold_pct"]:
                    a.status=REVIEW
                    a.warnings.append("Accepted pull-forward no longer fits below 85%; planner review")
            o = options[a.factory]
            alternatives = self._alternatives(lot, ledger, po_date, qty) if a.status == REVIEW else []
            if a.status != REVIEW:
                ledger.add(a.factory, o["start"], o["mfg"], qty)
            placed[id(lot)] = {"alternatives": alternatives, "factory": a.factory, "backup": a.routed_to_backup, "mfg": o["mfg"],
                               "trans": o["trans"], "release": o["release"], "start": o["start"], "rdd": rdd,
                               "qty": qty, "status": a.status, "util_before": o["before"], "util_after": o["after"],
                               "reasons": a.reasons, "warnings": a.warnings, "primary": primary}
        return ledger, placed

    def _alternatives(self, lot: Lot, ledger, po_date, qty: float) -> list[str]:
        """Options for a lot no chain factory had room for: every certified factory with its load (this lot
        added), arrival and cost, feasible ones first. The planner chooses; nothing here is bought."""
        hard = self.cfg["capacity"]["hard_limit_pct"]
        rdd = self._min_rdd(lot.pr_ids)
        unit_cost = self.rows[lot.pr_ids[0]]["unit_cost_usd"]
        start = pd.Timestamp(po_date)
        out = []
        for f in sorted(self.certified[lot.article_id]):
            m, t = self.lot_lead_times(lot.pr_ids, f)
            load = ledger.utilization_with(f, start, m, qty)
            arrival = timing.delivery_date(start, m, t)
            cost = qty * unit_cost * float(self.factories.loc[f, "cost_multiplier"])
            out.append((load > hard, load, f"{f}: {load:.0f}% with this lot ({'fits' if load <= hard else 'over limit'}), "
                        f"arrives {arrival:%Y-%m-%d}{' on time' if arrival <= rdd else ' late'}, ${cost:,.0f}"))
        return [text for _, _, text in sorted(out)]

    def _check_mpq(self, placed, lots, candidates, used_future, run_id, next_buy, tol):
        """MPQ per article per factory for the window. Lots sent to planner review are not produced
        and do not count towards a factory's total."""
        mpq_cfg = self.cfg["quantities"]["mpq"]
        groups: dict[tuple, list[Lot]] = {}
        changed, keep = False, []
        for lot in lots:
            if placed[id(lot)]["status"] == REVIEW:
                keep.append(lot)
                continue
            groups.setdefault((lot.article_id, placed[id(lot)]["factory"]), []).append(lot)
        date_groups = []
        for (article, factory), members in groups.items():
            bands = []
            for lot in sorted(members, key=lambda l: self._min_rdd(l.pr_ids)):
                if bands and self.rdd_span_ok([p for l in bands[-1] for p in l.pr_ids] + lot.pr_ids):
                    bands[-1].append(lot)
                else:
                    bands.append([lot])
            date_groups.extend((article, factory, band) for band in bands)
        for article, factory, glots in date_groups:
            category = self.rows[glots[0].pr_ids[0]]["category"]
            mpq = mpq_for(category, mpq_cfg)
            total = sum(self._qty(l.pr_ids) for l in glots)
            status = quantity_status(total, mpq, tol)
            if status == PIGGYBACK:
                markets = sorted({l.market for l in glots})
                base_ids = [p for l in glots for p in l.pr_ids]
                c = candidates(article, markets, base_ids)
                picked = pick_to_fill(mpq - total, list(zip(c["pr_id"], c["requested_qty"])))
                if picked and self.rdd_span_ok(base_ids + picked):
                    for p in picked:
                        target = next(l for l in glots if l.market == self.rows[p]["market_destination"])
                        self._apply_piggyback(target, [p], used_future,
                                              f"Rule 4: {factory} total {total:.0f} was within {tol}% of MPQ {mpq}")
                    keep.extend(glots)
                    changed = True
                    continue
            if status == OK or quantity_status(total, mpq, tol) == OK:
                for l in glots:
                    if not any(r.startswith("Rule 3: MPQ") for r in l.reasons):
                        l.reasons.append(f"Rule 3: MPQ {mpq} met at {factory} ({total:.0f} units this window)")
                keep.extend(glots)
            elif any(l.last_chance for l in glots):
                for l in glots:
                    l.warnings.append(f"Below MPQ: {total:.0f} < {mpq} at {factory}, bought anyway (last chance)")
                keep.extend(glots)
            else:
                changed = True
                all_ids = [p for l in glots for p in l.pr_ids]
                if all(self._can_wait(l.pr_ids, next_buy) for l in glots):
                    for p in all_ids:
                        self.open[p] = f"Rule 3: {factory} total {total:.0f} below MPQ {mpq}; waiting for more demand"
                    for l in glots:  # piggybacked demand goes back to the open pool
                        used_future.difference_update(l.pr_ids)
                else:
                    pulled = {p for l in glots for p in l.piggyback_prs}
                    used_future.difference_update(pulled)
                    self._decide([p for p in all_ids if p not in pulled], run_id, UNRESOLVED_MPQ,
                                 f"Rule 3: {factory} total {total:.0f} below MPQ {mpq} and cannot wait for the next window")
        return changed, keep

    def _lot_row(self, lot: Lot, a: dict, notes, buy_date, draft: bool) -> dict:
        prs = self.prs.loc[lot.pr_ids]
        f = self.factories.loc[a["factory"]]
        arrival = timing.delivery_date(a["start"],a["mfg"],a["trans"])
        on_time_units = float(prs.loc[prs["rdd_original"] >= arrival, "requested_qty"].sum())
        warnings = list(lot.warnings) + list(a["warnings"])
        if a["release"] < a["start"]:
            warnings.append(f"Late start: release {a['release']:%Y-%m-%d} was before PO date; "
                            f"production starts {a['start']:%Y-%m-%d}")
        if arrival > a["rdd"]:
            warnings.append(f"Late arrival: expected {arrival:%Y-%m-%d} vs RDD {a['rdd']:%Y-%m-%d}")
        reasons = []
        for p in lot.pr_ids:
            for n in notes.get(p, []):
                if n.startswith(("Rule 5", "Rule 6")) and n not in reasons:
                    reasons.append(n)
        rule1 = next((n for p in lot.pr_ids for n in notes.get(p, []) if n.startswith("Rule 1")), None)
        if rule1:
            reasons.insert(0, rule1)
        review = a["status"] == REVIEW
        # a review lot is not produced, so an MPQ note from an earlier assignment pass no longer applies
        reasons += [r for r in lot.reasons if not (review and r.startswith("Rule 3: MPQ"))] + a["reasons"]
        unit_cost = float(prs["unit_cost_usd"].iloc[0])
        primary_mult = float(self.factories.loc[a["primary"], "cost_multiplier"])
        return {
            "lot_id": lot.lot_id, "run_id": lot.run_id, "plan_status": DRAFT if draft else COMMITTED,
            "buying_window": window_label(buy_date), "auto_decision": "Review" if review else "Buy",
            "capacity_status": STATUS_LABELS[a["status"]],
            "util_before_pct": round(float(a["util_before"]), 1), "util_after_pct": round(float(a["util_after"]), 1),
            "mfg_days": float(a["mfg"]), "article_id": lot.article_id,
            "category": prs["category"].iloc[0], "market_destination": lot.market,
            "consolidated_qty": int(prs["requested_qty"].sum()), "n_prs": len(lot.pr_ids),
            "pr_ids": ",".join(lot.pr_ids), "earliest_rdd": a["rdd"],
            "suggested_rdd": arrival,
            "inventory_exposure_days": int((arrival - a["rdd"]).days),
            "inventory_exposure_basis": "versus earliest original RDD; PR-level differences in detail",
            "primary_factory": a["primary"], "assigned_factory": a["factory"],
            "backup_routed": a["backup"], "release_date": a["release"], "production_start": a["start"],
            "lead_time_source": ("PR-provided" if all(a["factory"] == self.rows[p]["assigned_factory"] for p in lot.pr_ids)
                                 else "Factory-midpoint estimate (mixed with PR values if applicable)"),
            "trans_days": float(a["trans"]),
            "on_time": arrival <= a["rdd"], "on_time_units": on_time_units,
            "unit_cost_usd": unit_cost, "cost_multiplier": float(f["cost_multiplier"]),
            "total_cost_usd": float(prs["requested_qty"].sum()) * unit_cost * float(f["cost_multiplier"]),
            "cost_delta_vs_primary_usd": float(prs["requested_qty"].sum()) * unit_cost
                                         * (float(f["cost_multiplier"]) - primary_mult),
            "nsv_usd": float(prs["nsv"].sum()),
            "is_piggyback_applied": bool(lot.piggyback_sources),
            "piggyback_source_window": ",".join(lot.piggyback_sources) or None,
            "last_chance": lot.last_chance, "decision_type": lot.decision_type,
            "alternatives": " | ".join(a.get("alternatives", [])),
            "reason": " | ".join(reasons), "warnings": " | ".join(warnings),
        }

    # ---------------------------------------------------------------- outputs
    def open_reason(self, pr_id: str, run_id: str) -> str:
        return self.results[run_id].open_reasons.get(pr_id, "Not yet due; carried to later runs")

    def run_result(self, run_id: str) -> RunResult:
        self.plan_through(run_id)
        return self.results[run_id]

    def all_lots(self) -> pd.DataFrame:
        """Committed lots from every buying run (bought and sent to planner review). Drafts are not included."""
        return pd.DataFrame(self.lot_rows)

    def bought_lots(self) -> pd.DataFrame:
        lots = self.all_lots()
        if not len(lots):
            return lots
        decisions = lots["decision"].fillna(lots["auto_decision"]) if "decision" in lots else lots["auto_decision"]
        return lots[decisions == "Buy"]

    def buying_runs(self) -> list[str]:
        return [r for r in self.runs["run_id"] if self.calendar.is_window(
            pd.Timestamp(self.runs.loc[self.run_index[r], "po_execution_date"]))]

    def pr_outcomes(self) -> pd.DataFrame:
        """One row per requisition seen so far: its final (or current open) outcome."""
        rows = [o for p, o in self.outcomes.items() if p not in self.open]
        rows += [{"pr_id": p, "decided_in_run": None, "outcome": self.outcomes.get(p, {}).get("outcome", OPEN), "lot_id": None, "reason": r}
                 for p, r in self.open.items()]
        out = pd.DataFrame(rows)
        return out.merge(self.prs[["pr_id", "run_id", "article_id", "market_destination", "channel_id",
                                   "requested_qty", "rdd_original", "nsv", "customer_id"]].reset_index(drop=True),
                         on="pr_id", how="left")
