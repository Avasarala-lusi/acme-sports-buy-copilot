"""Persist decisions and replay subsequent demand and capacity; never mutate the reference.

Hold and Delay apply to one buying window; No-Go cancels the selected PRs until
reverted. Approving a lot never bypasses certification, quantity or capacity checks.
"""
import hashlib
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import pandas as pd
from engine.config import ROOT, load_config
from engine.planner import BOUGHT, PLANNER_REVIEW, Planner
from engine.rules.quantities import mpq_for
from engine.rules.timing import delivery_date

DECISIONS = ["Buy", "No-Go", "Delay"]


def ensure_decidable(planner, run_id):
    if not planner.run_result(run_id).is_buying_run:
        raise ValueError(f"{run_id} is a draft; decisions are made in the buying run")


class OverrideStore:
    def __init__(self, path=None):
        self.path = Path(path or ROOT / load_config()["data"]["output_dir"] / "overrides.json")
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2))

    def run(self, run_id):
        return self.data.setdefault(run_id, {"lots": {}, "held_customers": [], "pulls": []})

    def replay(self, planner):
        base = getattr(planner, "automatic_reference", planner)
        if not self.data:
            return base
        key = hashlib.sha256(json.dumps(self.data, sort_keys=True).encode()).hexdigest()
        cached = getattr(base, "_decision_replay", None)
        if cached and cached[0] == key:
            return cached[1]
        effective = Planner(data=base.data, config=deepcopy(base.cfg), decisions=deepcopy(self.data))
        effective.automatic_reference = base
        base._decision_replay = (key, effective)
        return effective

    def set_lot(self, planner, run_id, lot_id, decision="Buy", factory=None, note=""):
        ensure_decidable(planner, run_id)
        lots = planner.run_result(run_id).lots.set_index("lot_id")
        if lot_id not in lots.index:
            raise KeyError(f"unknown lot {lot_id}")
        if decision not in DECISIONS and decision != "Review":
            raise ValueError(f"decision must be one of {DECISIONS}")
        lot = lots.loc[lot_id]
        if factory and factory not in planner.certified[lot.article_id]:
            raise ValueError(f"{factory} is not certified for {lot.article_id}")
        if decision == lot.auto_decision and not factory and not note:
            self.run(run_id)["lots"].pop(lot_id, None)
        else:
            self.run(run_id)["lots"][lot_id] = {"decision": decision, "factory": factory,
                "note": note, "pr_ids": lot.pr_ids.split(","),
                "updated_at": datetime.now().isoformat(timespec="seconds")}
        self.save()

    def revert_lot(self, run_id, lot_id):
        self.run(run_id)["lots"].pop(lot_id, None)
        self.save()

    def hold_customer(self, run_id, customer_id):
        held = self.run(run_id)["held_customers"]
        if customer_id not in held:
            held.append(customer_id)
        self.save()

    def release_customer(self, run_id, customer_id):
        held = self.run(run_id)["held_customers"]
        if customer_id in held:
            held.remove(customer_id)
        self.save()

    def reset(self, run_id):
        self.data.pop(run_id, None)
        self.save()

    def accept_pull(self, planner, run_id, pr_ids, target_run_id):
        from engine.pull_forward import recommendations
        matches=[r for r in recommendations(planner,run_id).to_dict("records")
                 if r["actionable"] and set(r["pr_ids"])==set(pr_ids) and r["target_run_id"]==target_run_id]
        if len(matches)!=1:
            raise ValueError("Pull-forward is not feasible in the current plan; refresh and review failed checks")
        row=matches[0]
        moves=self.run(target_run_id).setdefault("pulls",[])
        if any(set(m["pr_ids"]) & set(pr_ids) for m in moves):
            raise ValueError("These PRs already have an accepted pull-forward")
        moves.append({"pr_ids":pr_ids,"factory":row["factory_id"],"source_run_id":row["source_run_id"]})
        self.save()

    def count(self, run_id):
        r = self.data.get(run_id, {})
        return len(r.get("lots", {})) + len(r.get("held_customers", [])) + len(r.get("pulls", []))


def apply_run_decisions(planner, run_id, rows, buy_date, decisions):
    """Rebuild this run on prior commitments, with one shared ledger for all changes."""
    ledger = planner.ledger.copy()
    overrides = decisions.get("lots", {})
    held = set(decisions.get("held_customers", []))
    records, matched = [], set()
    for original in sorted(rows, key=lambda r: planner.priority_key(r["pr_ids"].split(","))):
        row = dict(original)
        ids = row["pr_ids"].split(",")
        found = [(k,v) for k,v in overrides.items() if k == row["lot_id"]
                 or (v.get("pr_ids") and set(v["pr_ids"]) == set(ids))]
        ov = found[0][1] if found else {}
        matched.update(k for k,_ in found)
        keep = [p for p in ids if planner.rows[p]["customer_id"] not in held]
        for p in set(ids)-set(keep):
            planner.outcomes.pop(p,None)
            planner.open[p]="Customer held for this buying window; reconsider next window"
        row.update(decision=ov.get("decision",row["auto_decision"]), override_note=ov.get("note",""))
        if ov or len(keep)!=len(ids):
            row["decision_type"]="manual"
        if len(keep)!=len(ids):
            row["override_note"] += f" Customer hold removed {planner._qty(set(ids)-set(keep)):g} units."
        if not keep:
            row.update(decision="No-Go",consolidated_qty=0,pr_ids="",n_prs=0,
                       total_cost_usd=0.,nsv_usd=0.,on_time_units=0.)
            row["override_note"] += " All customer units held for this window."
            records.append(row)
            continue
        qty = planner._qty(keep)
        factory = ov.get("factory") or row["assigned_factory"]
        m,t = planner.lot_lead_times(keep,factory)
        arrival = delivery_date(buy_date,m,t)
        rdd = planner._min_rdd(keep)
        load = ledger.utilization_with(factory,buy_date,m,qty)
        row.update(pr_ids=",".join(keep),n_prs=len(keep),consolidated_qty=qty,
            assigned_factory=factory,mfg_days=m,trans_days=t,production_start=buy_date,
            release_date=rdd-pd.Timedelta(days=m+t),earliest_rdd=rdd,suggested_rdd=arrival,
            inventory_exposure_days=int((arrival-rdd).days),
            lead_time_source="PR-provided" if all(planner.rows[p]["assigned_factory"]==factory for p in keep)
                else "Factory-midpoint estimate (mixed with PR values if applicable)",
            cost_multiplier=float(planner.factories.loc[factory,"cost_multiplier"]),
            total_cost_usd=qty*row["unit_cost_usd"]*float(planner.factories.loc[factory,"cost_multiplier"]),
            cost_delta_vs_primary_usd=qty*row["unit_cost_usd"]*(float(planner.factories.loc[factory,"cost_multiplier"])
                -float(planner.factories.loc[row["primary_factory"],"cost_multiplier"])),
            nsv_usd=sum(planner.rows[p]["nsv"] for p in keep),on_time=arrival<=rdd,
            on_time_units=sum(planner.rows[p]["requested_qty"] for p in keep if arrival<=planner.rows[p]["rdd_original"]),
            util_before_pct=round(ledger.utilization(factory,ledger.weeks_for(buy_date,m)),1),
            util_after_pct=round(load,1),backup_routed=factory!=row["primary_factory"])
        if row["decision"]=="Buy":
            failures=[]
            if factory not in planner.certified[row["article_id"]]: failures.append("uncertified factory")
            if load>planner.cfg["capacity"]["hard_limit_pct"]+1e-9: failures.append("hard capacity ceiling")
            if qty<planner.cfg["quantities"]["moq_per_market"] and not row["last_chance"]:
                failures.append("market MOQ after hold")
            if not planner.rdd_span_ok(keep): failures.append("15-day RDD span")
            if failures:
                row["decision"]="Review"
                row["warnings"] += " | Not committed: "+", ".join(failures)
            else:
                ledger.add(factory,buy_date,m,qty)
        records.append(row)
    for band in planner.mpq_groups([r for r in records if r["decision"]=="Buy"]):
        minimum=mpq_for(band[0]["category"],planner.cfg["quantities"]["mpq"])
        if sum(r["consolidated_qty"] for r in band)<minimum and not any(r["last_chance"] for r in band):
            for row in band:
                ledger.remove(row["assigned_factory"],buy_date,row["mfg_days"],row["consolidated_qty"])
                row["decision"]="Review"
                row["warnings"] += " | MPQ not met after planner changes; not committed"
    for row in records:
        row["capacity_status"] = ("Needs planner review" if row["decision"]=="Review" else
            "Above threshold, within capacity" if row["util_after_pct"]>=planner.cfg["capacity"]["backup_threshold_pct"]
            else "Within capacity")
        for p in filter(None,row["pr_ids"].split(",")):
            planner.outcomes.pop(p,None)
            if row["decision"]=="Buy":
                planner._decide([p],run_id,BOUGHT,"Planner-effective purchase",row["lot_id"])
            elif row["decision"]=="No-Go":
                planner._decide([p],run_id,"CANCELLED","Planner No-Go",row["lot_id"])
            elif row["decision"]=="Delay":
                planner.open[p]="Planner delayed to next buying window"
            else:
                planner._decide([p],run_id,PLANNER_REVIEW,row["warnings"],row["lot_id"])
    unmatched=overrides.keys()-matched
    for key in unmatched:
        planner.decision_issues.append(f"{run_id}/{key}: saved lot grouping changed; review/reapply decision")
    if unmatched:
        # Cannot safely associate an old decision with a new grouping. Fail closed
        # for this window rather than buying something the planner may have cancelled.
        ledger=planner.ledger.copy()
        for row in records:
            if row["decision"]=="Buy":
                row["decision"]="Review"
                row["capacity_status"]="Needs planner review"
                row["warnings"] += " | Unmatched saved decision: reapply before committing this window"
                planner._decide(row["pr_ids"].split(","),run_id,PLANNER_REVIEW,row["warnings"],row["lot_id"])
    return records,ledger


def effective_lots(planner,run_id,store):
    lots=store.replay(planner).run_result(run_id).lots.copy()
    if "decision" not in lots:
        lots["decision"]=lots.get("auto_decision",pd.Series(dtype=str))
    if "override_note" not in lots: lots["override_note"]=""
    return lots


def effective_fact_table(planner,run_id,store):
    from engine.output import SPEC_COLUMNS
    lots=effective_lots(planner,run_id,store)
    out=lots[(lots["decision"]=="Buy") & (lots["consolidated_qty"]>0)].copy()
    out["suggestion_id"]="SUG-"+out["lot_id"]
    out["suggested_rdd"]=pd.to_datetime(out["suggested_rdd"]).dt.date
    return out[SPEC_COLUMNS].reset_index(drop=True)
