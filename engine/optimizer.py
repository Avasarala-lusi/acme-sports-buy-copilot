"""Cost vs. service planning: one plan for all six factories at once (mixed-integer programme).

The rule engine decides lot by lot, walking each article's backup chain. The optimiser takes the same lots (the rule
plan's bought lots plus the lots it sent to planner review, each requisition once, in the first window it was due)
and chooses, for every lot, one certified factory or "not bought", for all buying windows together:

- capacity: every factory-week stays at or below the hard limit (100%), with the same business-day spread of a lot's
  units over its production weeks as the rule engine; closed factory-weeks (a disruption drill) have no capacity,
- MPQ (optional, on by default): a production order (article, factory, buying window) is either empty or reaches the
  category MPQ; last-chance lots are bought even below it, as in the rules,
- objective: (1 - w) x production cost + w x units expected late, with a large penalty for every unit not bought.
  w = 0 is the cheapest plan, w = 1 the safest (most units expected on time, using the lead-time variation in
  engine.risk). Both terms are per unit and of similar size, so the slider moves smoothly between them.

Lot contents (which requisitions, MOQ grouping) are kept as the rules built them; only the factory and the buy
decision change. Production starts on the window's PO date, as in the rules.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from engine.capacity import CapacityLedger
from engine.planner import Planner
from engine.risk import DelayModel
from engine.rules.quantities import mpq_for

SKIP_PENALTY = 3.0        # per unit not bought (costs and late units are about 1 per unit)
SKIP_PENALTY_LAST = 6.0   # last-chance demand: buy whenever there is any room


def universe(planner: Planner) -> pd.DataFrame:
    """Lots to plan: the rule plan's bought lots, plus review lots with each requisition kept once (first window)
    and never one that the rules bought later."""
    lots = planner.all_lots()
    # Newly exposed backlog rows are planner exceptions, not automatic optimizer
    # candidates (they may be below MOQ or conflict with forecast exclusion).
    if "review_only" in lots:
        lots = lots[~lots["review_only"].fillna(False)]
    decision = lots["auto_decision"]
    bought = lots[decision == "Buy"].copy()
    bought["rule_factory"] = bought["assigned_factory"]
    seen = {p for ids in bought["pr_ids"] for p in ids.split(",")}
    rows = []
    review = lots[decision == "Review"].copy()
    review["k"] = review["run_id"].map(planner.run_index)
    for r in review.sort_values(["k", "earliest_rdd"]).itertuples():
        ids = [p for p in r.pr_ids.split(",") if p not in seen]
        if not ids:
            continue
        seen.update(ids)
        rows.append({"lot_id": r.lot_id, "run_id": r.run_id, "article_id": r.article_id, "category": r.category,
                     "market_destination": r.market_destination, "primary_factory": r.primary_factory,
                     "pr_ids": ",".join(ids), "last_chance": r.last_chance, "rule_factory": None})
    cols = ["lot_id", "run_id", "article_id", "category", "market_destination", "primary_factory", "pr_ids",
            "last_chance", "rule_factory"]
    u = pd.concat([bought[cols], pd.DataFrame(rows, columns=cols)], ignore_index=True)
    u["qty"] = u["pr_ids"].map(lambda s: sum(planner.rows[p]["requested_qty"] for p in s.split(","))).astype(float)
    u["start"] = u["run_id"].map(lambda r: pd.Timestamp(planner.results[r].buy_date))
    u["season"] = u["run_id"].map(planner.runs.set_index("run_id")["season"])
    return u


def _closed(closures, factory, week) -> bool:
    return CapacityLedger({}, closures=closures).closed(factory, week) if closures else False


def options(planner: Planner, u: pd.DataFrame, model: DelayModel | None = None) -> pd.DataFrame:
    """Every certified factory for every lot: lead times, arrival, cost, late and expected on-time units, and the
    lot's units per production week."""
    model = model or DelayModel(planner)
    ledger = CapacityLedger(planner.factories["weekly_capacity_units"].to_dict(),
                            planner.cfg["capacity"]["spread_over_manufacturing"])
    mult = planner.factories["cost_multiplier"].astype(float).to_dict()
    rows = []
    for i, lot in enumerate(u.itertuples()):
        ids = lot.pr_ids.split(",")
        qty = np.array([planner.rows[p]["requested_qty"] for p in ids], dtype=float)
        rdd = pd.to_datetime([planner.rows[p]["rdd_original"] for p in ids])
        unit_cost = float(planner.rows[ids[0]]["unit_cost_usd"])
        for f in sorted(planner.certified[lot.article_id]):
            m, t = planner.lot_lead_times(ids, f)
            arrival = (lot.start + pd.Timedelta(days=float(m) + float(t))).normalize()
            slack = np.asarray((rdd - arrival).days, dtype=float)
            p = model.p_on_time(f, slack)
            rows.append({"lot": i, "factory": f, "mfg": float(m), "trans": float(t), "arrival": arrival,
                         "cost": lot.qty * unit_cost * mult[f], "on_time_units": float(qty[slack >= 0].sum()),
                         "expected_on_time_units": float((qty * p).sum()),
                         "alloc": ledger.allocations(lot.start, m, lot.qty)})
    return pd.DataFrame(rows)


def solve(planner: Planner, weight: float, u: pd.DataFrame | None = None, opts: pd.DataFrame | None = None,
          closures=None, enforce_mpq: bool | None = None, time_limit: float | None = None) -> dict:
    """Optimal factory (or not bought) per lot for the cost/service weight. Returns the choice and its KPIs."""
    cfg = planner.cfg.get("optimizer", {})
    enforce_mpq = cfg.get("enforce_mpq", True) if enforce_mpq is None else enforce_mpq
    time_limit = float(time_limit or cfg.get("time_limit_s", 60))
    u = universe(planner) if u is None else u
    opts = options(planner, u) if opts is None else opts
    t0 = time.time()
    n_opt, n_lot = len(opts), len(u)
    qty = u["qty"].to_numpy()
    o_qty = qty[opts["lot"].to_numpy()]
    avg_unit_cost = float(opts["cost"].sum() / o_qty.sum())
    w = float(np.clip(weight, 0, 1))
    late = o_qty - opts["expected_on_time_units"].to_numpy()
    c_opt = (1 - w) * opts["cost"].to_numpy() / avg_unit_cost + w * late
    c_opt += 1e-3 * (opts["cost"].to_numpy() / avg_unit_cost + late)  # break ties on both
    # prefer the primary factory: a backup must earn its place (cost or on-time), as the client asked for fewer backups
    backup = opts["factory"].to_numpy() != u["primary_factory"].to_numpy()[opts["lot"]]
    c_opt += float(cfg.get("backup_penalty_per_unit", 0.1)) * o_qty * backup
    c_skip = qty * np.where(u["last_chance"].to_numpy(), SKIP_PENALTY_LAST, SKIP_PENALTY)

    # production orders for MPQ: (run, article, factory)
    keys = list(zip(u["run_id"].to_numpy()[opts["lot"]], u["article_id"].to_numpy()[opts["lot"]], opts["factory"]))
    order_ids = {k: j for j, k in enumerate(dict.fromkeys(keys))} if enforce_mpq else {}
    n_y = len(order_ids)
    n = n_opt + n_lot + n_y
    c = np.concatenate([c_opt, c_skip, np.zeros(n_y)])

    rows, cols, vals, lo, hi = [], [], [], [], []
    r = 0
    # each lot: one factory or skipped
    for i, lot_opts in opts.groupby("lot").groups.items():
        rows += [r] * (len(lot_opts) + 1)
        cols += list(lot_opts) + [n_opt + i]
        vals += [1.0] * (len(lot_opts) + 1)
        lo.append(1.0); hi.append(1.0); r += 1
    # capacity per factory-week
    hard = planner.cfg["capacity"]["hard_limit_pct"] / 100
    cap = planner.factories["weekly_capacity_units"].astype(float).to_dict()
    fw: dict[tuple, int] = {}
    for j, (f, alloc) in enumerate(zip(opts["factory"], opts["alloc"])):
        for week, units in alloc:
            k = fw.setdefault((f, week), len(fw))
            rows.append(r + k); cols.append(j); vals.append(float(units))
    for (f, week) in fw:
        lo.append(-np.inf); hi.append(0.0 if _closed(closures, f, week) else cap[f] * hard)
    r += len(fw)
    # MPQ: x <= y for non-last-chance lots; sum(qty x) >= MPQ y
    if enforce_mpq:
        last = u["last_chance"].to_numpy()[opts["lot"]]
        for j, k in enumerate(keys):
            if not last[j]:
                rows += [r, r]; cols += [j, n_opt + n_lot + order_ids[k]]; vals += [1.0, -1.0]
                lo.append(-np.inf); hi.append(0.0); r += 1
        mpq_cfg = planner.cfg["quantities"]["mpq"]
        cat = dict(zip(u["article_id"], u["category"]))
        for j, k in enumerate(keys):
            rows.append(r + order_ids[k]); cols.append(j); vals.append(float(o_qty[j]))
        for k, y in order_ids.items():
            rows.append(r + y); cols.append(n_opt + n_lot + y); vals.append(-float(mpq_for(cat[k[1]], mpq_cfg)))
            lo.append(0.0); hi.append(np.inf)
        r += n_y
    A = coo_matrix((vals, (rows, cols)), shape=(r, n)).tocsr()
    res = milp(c, constraints=LinearConstraint(A, lo, hi), integrality=np.ones(n), bounds=Bounds(0, 1),
               options={"time_limit": time_limit, "mip_rel_gap": float(cfg.get("mip_gap", 0.005)), "disp": False})
    if res.x is None:
        raise RuntimeError(f"optimiser found no plan: {res.message}")
    x = res.x[:n_opt] > 0.5
    chosen = pd.Series(-1, index=range(n_lot))
    chosen[opts.loc[x, "lot"].to_numpy()] = np.flatnonzero(x)
    return {"weight": w, "choice": chosen, "status": res.message,
            "gap_pct": float(getattr(res, "mip_gap", None) or 0) * 100, "objective": float(res.fun),
            "seconds": time.time() - t0, "u": u, "opts": opts}


def rule_choice(u: pd.DataFrame, opts: pd.DataFrame) -> pd.Series:
    """The rule engine's plan in the same terms: its factory for bought lots, not bought for review lots."""
    idx = {(l, f): j for j, (l, f) in enumerate(zip(opts["lot"], opts["factory"]))}
    return pd.Series([idx.get((i, f), -1) if isinstance(f, str) else -1 for i, f in enumerate(u["rule_factory"])])


def evaluate(planner: Planner, u: pd.DataFrame, opts: pd.DataFrame, choice: pd.Series,
             mask: pd.Series | None = None, closures=None) -> dict:
    """KPIs of a plan (choice per lot) on the lots in `mask` (all by default)."""
    mask = pd.Series(True, index=u.index) if mask is None else mask
    sel = choice[mask.to_numpy()]
    o = opts.loc[sel[sel >= 0].to_numpy()]
    lots = u[mask.to_numpy()]
    total = float(lots["qty"].sum())
    bought = float(u.loc[o["lot"], "qty"].sum())
    cost = float(o["cost"].sum())
    primary = u.loc[o["lot"], "primary_factory"].to_numpy()
    # capacity use of the lots evaluated (a season's lots alone when masked)
    ledger = CapacityLedger(planner.factories["weekly_capacity_units"].to_dict(),
                            planner.cfg["capacity"]["spread_over_manufacturing"])
    for f, alloc in zip(o["factory"], o["alloc"]):
        for week, units in alloc:
            ledger.units[f][week] += units
    t = ledger.table()
    closed = t.apply(lambda r: _closed(closures, r["factory_id"], r["week"]), axis=1) if len(t) and closures else None
    over = int((t["utilization_pct"] > 100.0001).sum()) if len(t) else 0
    mpq_cfg = planner.cfg["quantities"]["mpq"]
    orders = (pd.DataFrame({"run": u.loc[o["lot"], "run_id"].to_numpy(), "article": u.loc[o["lot"], "article_id"].to_numpy(),
                            "cat": u.loc[o["lot"], "category"].to_numpy(), "f": o["factory"].to_numpy(),
                            "q": u.loc[o["lot"], "qty"].to_numpy(), "lc": u.loc[o["lot"], "last_chance"].to_numpy()})
              .groupby(["run", "article", "f"]).agg(q=("q", "sum"), cat=("cat", "first"), lc=("lc", "any")))
    below = orders[(orders["q"] < orders["cat"].map(lambda c: mpq_for(c, mpq_cfg))) & ~orders["lc"]] if len(orders) else orders
    return {
        "firm_units": total, "units_bought": bought, "units_not_bought": total - bought,
        "bought_pct": bought / total * 100 if total else 0.0,
        "production_cost_usd": cost, "cost_per_unit_usd": cost / bought if bought else 0.0,
        "on_time_units": float(o["on_time_units"].sum()),
        "on_time_pct_of_bought": float(o["on_time_units"].sum()) / bought * 100 if bought else 0.0,
        "on_time_pct_of_firm": float(o["on_time_units"].sum()) / total * 100 if total else 0.0,
        "expected_on_time_units": float(o["expected_on_time_units"].sum()),
        "expected_on_time_pct_of_bought": float(o["expected_on_time_units"].sum()) / bought * 100 if bought else 0.0,
        "backup_units_pct": float(u.loc[o["lot"], "qty"].to_numpy()[o["factory"].to_numpy() != primary].sum()) / bought * 100
        if bought else 0.0,
        "peak_utilization_pct": float(t["utilization_pct"].max()) if len(t) else 0.0,
        "weeks_over_100": over,
        "units_in_closed_weeks": float(t.loc[closed, "units"].sum()) if closed is not None else 0.0,
        "orders_below_mpq": int(len(below)),
    }


def evaluate_as_is(planner: Planner, u: pd.DataFrame, model: DelayModel, mask: pd.Series | None = None) -> dict:
    """Today's assignments on the same requisitions: each at its supplied factory with its own lead times, starting
    on the PO date of the run it appeared in, everything bought, capacity ignored (as in the baseline evaluation)."""
    mask = pd.Series(True, index=u.index) if mask is None else mask
    ids = [p for s in u.loc[mask.to_numpy(), "pr_ids"] for p in s.split(",")]
    prs = planner.prs.loc[ids]
    po = prs["run_id"].map(planner.runs.set_index("run_id")["po_execution_date"]).map(pd.Timestamp)
    m, t = prs["manufacturing_lead_time"].astype(float), prs["transportation_lead_time"].astype(float)
    arrival = (po + pd.to_timedelta(m + t, unit="D")).dt.normalize()
    slack = (prs["rdd_original"] - arrival).dt.days.astype(float).to_numpy()
    qty = prs["requested_qty"].astype(float).to_numpy()
    f = prs["assigned_factory"].to_numpy()
    mult = prs["assigned_factory"].map(planner.factories["cost_multiplier"].astype(float)).to_numpy()
    cost = float((qty * prs["unit_cost_usd"].astype(float).to_numpy() * mult).sum())
    p = model.p_on_time(f, slack)
    ledger = CapacityLedger(planner.factories["weekly_capacity_units"].to_dict(),
                            planner.cfg["capacity"]["spread_over_manufacturing"])
    for fac, start, mfg, q in zip(f, po, m, qty):
        ledger.add(fac, start, mfg, q)
    tb = ledger.table()
    total = float(qty.sum())
    on_time = float(qty[slack >= 0].sum())
    return {
        "firm_units": total, "units_bought": total, "units_not_bought": 0.0, "bought_pct": 100.0,
        "production_cost_usd": cost, "cost_per_unit_usd": cost / total if total else 0.0,
        "on_time_units": on_time, "on_time_pct_of_bought": on_time / total * 100 if total else 0.0,
        "on_time_pct_of_firm": on_time / total * 100 if total else 0.0,
        "expected_on_time_units": float((qty * p).sum()),
        "expected_on_time_pct_of_bought": float((qty * p).sum()) / total * 100 if total else 0.0,
        "backup_units_pct": float(qty[prs["backup_triggered"].to_numpy().astype(bool)].sum()) / total * 100 if total else 0.0,
        "peak_utilization_pct": float(tb["utilization_pct"].max()) if len(tb) else 0.0,
        "weeks_over_100": int((tb["utilization_pct"] > 100.0001).sum()) if len(tb) else 0,
        "units_in_closed_weeks": 0.0, "orders_below_mpq": None,
    }


def by_factory(u: pd.DataFrame, opts: pd.DataFrame, choice: pd.Series) -> list[dict]:
    o = opts.loc[choice[choice >= 0].to_numpy()].copy()
    o["qty"] = u.loc[o["lot"], "qty"].to_numpy()
    g = o.groupby("factory").agg(units=("qty", "sum"), cost=("cost", "sum"), on_time=("on_time_units", "sum"))
    return [{"factory_id": f, "units": float(r.units), "production_cost_usd": float(r.cost),
             "on_time_pct": float(r.on_time / r.units * 100) if r.units else 0.0} for f, r in g.iterrows()]


def changes(u: pd.DataFrame, opts: pd.DataFrame, rule: pd.Series, plan: pd.Series, top: int = 300) -> list[dict]:
    """Lots the optimiser plans differently from the rules, largest first."""
    out = []
    for i in np.flatnonzero(rule.to_numpy() != plan.to_numpy()):
        lot = u.iloc[i]
        a, b = rule.iloc[i], plan.iloc[i]
        oa = opts.loc[a] if a >= 0 else None
        ob = opts.loc[b] if b >= 0 else None
        out.append({"lot_id": lot["lot_id"], "run_id": lot["run_id"], "article_id": lot["article_id"],
                    "market_destination": lot["market_destination"], "qty": float(lot["qty"]),
                    "rule_factory": oa["factory"] if oa is not None else None,
                    "plan_factory": ob["factory"] if ob is not None else None,
                    "rule_on_time_units": float(oa["on_time_units"]) if oa is not None else 0.0,
                    "plan_on_time_units": float(ob["on_time_units"]) if ob is not None else 0.0,
                    "cost_change_usd": (float(ob["cost"]) if ob is not None else 0.0) - (float(oa["cost"]) if oa is not None else 0.0)})
    return sorted(out, key=lambda r: -r["qty"])[:top]


class Network:
    """Universe and options built once; solves and evaluations reuse them."""

    def __init__(self, planner: Planner):
        self.planner = planner
        self.model = DelayModel(planner)
        self.u = universe(planner)
        self.opts = options(planner, self.u, self.model)
        self.rule = rule_choice(self.u, self.opts)

    def solve(self, weight: float, closures=None, **kw) -> dict:
        return solve(self.planner, weight, self.u, self.opts, closures=closures, **kw)

    def report(self, weight: float) -> dict:
        s = self.solve(weight)
        return {"weight": s["weight"], "status": s["status"], "seconds": s["seconds"],
                "rule": evaluate(self.planner, self.u, self.opts, self.rule),
                "plan": evaluate(self.planner, self.u, self.opts, s["choice"]),
                "rule_by_factory": by_factory(self.u, self.opts, self.rule),
                "plan_by_factory": by_factory(self.u, self.opts, s["choice"]),
                "changes": changes(self.u, self.opts, self.rule, s["choice"])}
