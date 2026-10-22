"""What-if scenarios

Each scenario works on a copy of one run's plan and never changes the baseline.
Every changed lot is marked decision_type = "manual". Capacity effects are recalculated on a copy
of the run's capacity ledger, with the change applied.
"""
import pandas as pd

from engine.planner import Planner
from engine.rules.quantities import mpq_for, pick_to_fill
from engine.rules.timing import delivery_date

def _run_lots(planner: Planner, run_id: str) -> pd.DataFrame:
    return planner.run_result(run_id).lots.copy()


def _bought(lots: pd.DataFrame) -> pd.DataFrame:
    return lots[lots.get("decision",lots["auto_decision"]).fillna(lots["auto_decision"]) == "Buy"] if len(lots) else lots


def _qty(planner: Planner, ids) -> float:
    return float(sum(planner.rows[p]["requested_qty"] for p in ids))


def _future_candidates(planner: Planner, run_id: str, article: str, market: str,
                       exclude_customer: str | None = None, reserved: set | None = None) -> pd.DataFrame:
    """Open demand of the same article and market, earliest RDD first, that a fix may pull forward.
    Never the held customer's own demand, and never a requisition already used by another fix."""
    open_ids = planner.run_result(run_id).open_prs
    f = planner.prs.loc[open_ids] if open_ids else planner.prs.iloc[0:0]
    f = f[(f["article_id"] == article) & (f["market_destination"] == market)]
    if exclude_customer is not None:
        f = f[f["customer_id"].fillna("") != exclude_customer]
    if reserved:
        f = f[~f["pr_id"].isin(reserved)]
    return f.sort_values("rdd_original")


def check_minimums(planner: Planner, run_id: str, lots: pd.DataFrame, qty_col: str,
                   exclude_customer: str | None = None) -> pd.DataFrame:
    """Scenario 2: MOQ cascade. Flags lots that fall below MOQ and proposes a same-market fix.

    Each candidate requisition is reserved once chosen, so two lots never claim the same demand.
    """
    moq = planner.cfg["quantities"]["moq_per_market"]
    reserved: set[str] = set()
    rows = []
    original_lots=planner.run_result(run_id).lots.set_index("lot_id")
    for lot in lots.itertuples():
        qty = getattr(lot, qty_col)
        base = {"lot_id": lot.lot_id, "pulled_pr_ids": ""}
        if qty == 0:
            rows.append({**base, "moq_ok": True, "fix": "Lot fully held: no units left to buy",
                         "qty_after_fix": 0, "suggested_rdd_after_fix": None})
            continue
        if qty >= moq:
            rows.append({**base, "moq_ok": True, "fix": None,
                         "qty_after_fix": qty, "suggested_rdd_after_fix": lot.suggested_rdd})
            continue
        c = _future_candidates(planner, run_id, lot.article_id, lot.market_destination, exclude_customer, reserved)
        base = {"lot_id": lot.lot_id, "pulled_pr_ids": ""}
        original = original_lots.loc[lot.lot_id]
        ids = [p for p in original.pr_ids.split(",") if planner.rows[p]["customer_id"] != exclude_customer]
        c = c.loc[c["pr_id"].map(lambda p: planner.rdd_span_ok(ids+[p]) and planner.eligible_pull(p,planner.results[run_id].buy_date)).astype(bool)]
        picked = pick_to_fill(moq - qty, list(zip(c["pr_id"], c["requested_qty"])))
        if picked and not planner.rdd_span_ok(ids+picked):
            picked=[]
        if picked:
            reserved.update(picked)
            added = c.set_index("pr_id").loc[picked]
            fix = (f"Pull {added['requested_qty'].sum():.0f} units forward from {len(picked)} future "
                   f"{lot.market_destination} requisition(s) of {lot.article_id}"
                   + (f", none from {exclude_customer}" if exclude_customer else ""))
            rows.append({**base, "moq_ok": False, "fix": fix, "pulled_pr_ids": ",".join(picked),
                         "qty_after_fix": qty + added["requested_qty"].sum(),
                         "suggested_rdd_after_fix": delivery_date(planner.results[run_id].buy_date,
                             *planner.lot_lead_times(ids+picked,original.assigned_factory))})
        else:
            rows.append({**base, "moq_ok": False,
                         "fix": "No eligible same-market future demand to pull; hold for next window or accept below MOQ",
                         "qty_after_fix": qty, "suggested_rdd_after_fix": lot.suggested_rdd})
    return pd.DataFrame(rows)


def hold_customer(planner: Planner, run_id: str, customer_id: str) -> dict:
    """Scenario 1: put a customer on hold, remove their units, compute NSV at risk, and re-check
    MOQ, MPQ and factory load for the plan after the hold and any proposed fixes."""
    lots = _run_lots(planner, run_id)
    prs = planner.prs
    rows, sizes = [], []
    for lot in lots.itertuples():
        ids = lot.pr_ids.split(",")
        held_ids=[p for p in ids if planner.rows[p]["customer_id"]==customer_id]
        if not held_ids:
            continue
        held=prs.loc[held_ids]
        removed = float(held["requested_qty"].sum())
        rows.append({"lot_id": lot.lot_id, "article_id": lot.article_id,
                     "market_destination": lot.market_destination, "assigned_factory": lot.assigned_factory,
                     "qty_before": lot.consolidated_qty, "qty_removed": removed,
                     "qty_after": lot.consolidated_qty - removed,
                     "nsv_at_risk_usd": float(held["nsv"].sum()),
                     "suggested_rdd": lot.suggested_rdd, "decision_type": "manual"})
        for s in held.itertuples():
            sizes.append({"lot_id": lot.lot_id, "pr_id": s.pr_id, "size_id": s.size_id,
                          "qty_removed": s.requested_qty, "nsv_usd": s.nsv})
    affected = pd.DataFrame(rows)
    if affected.empty:
        return {"customer_id": customer_id, "lots_affected": 0, "nsv_at_risk_usd": 0.0,
                "lots": affected, "sizes": pd.DataFrame(sizes), "moq_alerts": pd.DataFrame()}
    minimums = check_minimums(planner, run_id, affected, "qty_after", exclude_customer=customer_id)
    affected = affected.merge(minimums, on="lot_id")
    affected = _recheck_after_hold(planner, run_id, lots, affected, customer_id)
    return {
        "customer_id": customer_id,
        "lots_affected": len(affected),
        "nsv_at_risk_usd": float(affected["nsv_at_risk_usd"].sum()),
        "lots": affected,
        "sizes": pd.DataFrame(sizes),
        "moq_alerts": affected[~affected["moq_ok"]],
    }


def _recheck_after_hold(planner: Planner, run_id: str, lots: pd.DataFrame, affected: pd.DataFrame, customer_id: str) -> pd.DataFrame:
    """MOQ, MPQ (per article per factory this window) and factory load after the hold and the fixes."""
    cfg = planner.cfg
    moq = cfg["quantities"]["moq_per_market"]
    ledger = planner.snapshots[run_id].copy()
    final = _bought(lots).set_index("lot_id")["consolidated_qty"].astype(float).to_dict()
    bought = _bought(lots).set_index("lot_id")
    for a in affected.itertuples():
        if a.lot_id not in bought.index:
            continue
        lot = bought.loc[a.lot_id]
        ids=[p for p in lot.pr_ids.split(",") if planner.rows[p]["customer_id"]!=customer_id]
        ids+=list(filter(None,a.pulled_pr_ids.split(",")))
        ledger.remove(lot["assigned_factory"],lot["production_start"],lot["mfg_days"],lot["consolidated_qty"])
        if ids:
            m,t=planner.lot_lead_times(ids,lot["assigned_factory"])
            ledger.add(lot["assigned_factory"],lot["production_start"],m,a.qty_after_fix)
            bought.loc[a.lot_id,"pr_ids"]=",".join(ids)
            bought.loc[a.lot_id,"mfg_days"]=m
        final[a.lot_id] = a.qty_after_fix
    totals = {}
    records=[]
    for lot_id,q in final.items():
        if q:
            record=bought.loc[lot_id].to_dict()
            record.update(lot_id=lot_id,consolidated_qty=q)
            record["earliest_rdd"]=planner._min_rdd(record["pr_ids"].split(","))
            records.append(record)
    for band in planner.mpq_groups(records):
        total=sum(r["consolidated_qty"] for r in band)
        for row in band: totals[row["lot_id"]]=total
    categories = lots.set_index("lot_id")["category"]
    out = []
    for a in affected.to_dict("records"):
        key = (a["article_id"], a["assigned_factory"])
        mpq = mpq_for(categories[a["lot_id"]], cfg["quantities"]["mpq"])
        if a["lot_id"] in bought.index:
            lot = bought.loc[a["lot_id"]]
            load = ledger.utilization(lot["assigned_factory"], ledger.weeks_for(lot["production_start"], lot["mfg_days"]))
        else:
            load = None
        total = totals.get(a["lot_id"], 0.0)
        a.update(moq_ok_after_fix=bool(a["qty_after_fix"] == 0 or a["qty_after_fix"] >= moq),
                 factory_total_after=total, mpq=mpq,
                 mpq_ok_after_fix=bool(total == 0 or total >= mpq),
                 factory_load_after_pct=None if load is None else round(float(load), 1))
        out.append(a)
    return pd.DataFrame(out)


def move_load(planner: Planner, run_id: str, lot_id: str, target: str) -> dict:
    """Factory loads if a lot moves to `target`: copy the run's ledger, take the lot out of its current
    factory, put it into the target, and measure both over the affected production weeks."""
    r = planner.run_result(run_id)
    lot = r.lots.set_index("lot_id").loc[lot_id]
    ids = lot["pr_ids"].split(",")
    qty = float(lot["consolidated_qty"])
    source = lot["assigned_factory"]
    ledger = planner.snapshots[run_id].copy()
    src_weeks = ledger.weeks_for(lot["production_start"], lot["mfg_days"])
    source_before = ledger.utilization(source, src_weeks)
    if lot.get("decision",lot["auto_decision"]) == "Buy":
        ledger.remove(source, lot["production_start"], lot["mfg_days"], qty)
    m, t = planner.lot_lead_times(ids, target)
    release = lot["earliest_rdd"] - pd.Timedelta(days=m + t)
    start = r.buy_date
    weeks = ledger.weeks_for(start, m)
    return {"mfg": m, "trans": t, "release": release, "start": start,
            "source_before_pct": float(source_before),
            "source_after_pct": float(ledger.utilization(source, src_weeks)),
            "target_before_pct": float(ledger.utilization(target, weeks)),
            "target_after_pct": float(ledger.utilization_with(target, start, m, qty))}


def delay_factory(planner: Planner, run_id: str, factory: str, days: int) -> dict:
    """Scenario 3: shift the last production date at a factory by N days."""
    lots = _bought(_run_lots(planner, run_id))
    lots = lots[lots["assigned_factory"] == factory] if len(lots) else lots
    prs = planner.prs
    rows, late_prs = [], []
    for lot in lots.itertuples():
        new_arrival = lot.suggested_rdd + pd.Timedelta(days=days)
        p = prs.loc[lot.pr_ids.split(",")]
        late = p[p["rdd_original"] < new_arrival]
        rows.append({"lot_id": lot.lot_id, "article_id": lot.article_id,
                     "market_destination": lot.market_destination, "qty": lot.consolidated_qty,
                     "rdd": lot.earliest_rdd, "arrival_before": lot.suggested_rdd,
                     "arrival_after": new_arrival, "late_after": bool(len(late)),
                     "late_units": float(late["requested_qty"].sum()),
                     "nsv_at_risk_usd": float(late["nsv"].sum()), "decision_type": "manual"})
        late_prs.append(late)
    late_all = pd.concat(late_prs) if late_prs else prs.iloc[0:0]
    customers = (late_all.groupby("customer_id", dropna=False)
                 .agg(units=("requested_qty", "sum"), nsv_at_risk_usd=("nsv", "sum"))
                 .reset_index().sort_values("nsv_at_risk_usd", ascending=False))
    out = pd.DataFrame(rows)
    return {"factory": factory, "days": days, "lots": out,
            "lots_late": int(out["late_after"].sum()) if len(out) else 0,
            "nsv_at_risk_usd": float(out["nsv_at_risk_usd"].sum()) if len(out) else 0.0,
            "customers": customers}


def swap_factory(planner: Planner, run_id: str, lot_id: str, target: str) -> dict:
    """Scenario 3b: manually move a lot to another factory; validate and show the deltas.

    Capacity is recalculated on a copy of the ledger with the lot removed from its factory and added
    to the target, and MPQ is re-checked at both factories for this window."""
    lots = _run_lots(planner, run_id).set_index("lot_id")
    lot = lots.loc[lot_id]
    if target not in planner.certified[lot["article_id"]]:
        return {"valid": False,
                "message": f"{target} is not certified for {lot['article_id']} (certification matrix)"}
    cfg = planner.cfg
    ids = lot["pr_ids"].split(",")
    move = move_load(planner, run_id, lot_id, target)
    arrival = delivery_date(move["start"],move["mfg"],move["trans"])
    mult = float(planner.factories.loc[target, "cost_multiplier"])
    new_cost = lot["consolidated_qty"] * lot["unit_cost_usd"] * mult
    m0, t0 = planner.lot_lead_times(ids, lot["assigned_factory"])
    moq = cfg["quantities"]["moq_per_market"]
    mpq = mpq_for(lot["category"], cfg["quantities"]["mpq"])
    same = _bought(lots.reset_index())
    same = same[same["article_id"] == lot["article_id"]]
    same=same.loc[same["pr_ids"].map(lambda s: planner.rdd_span_ok(ids+s.split(","))).astype(bool)]
    at = lambda f: float(same.loc[same["assigned_factory"] == f, "consolidated_qty"].sum())
    qty = float(lot["consolidated_qty"]) if lot["auto_decision"] == "Buy" else 0.0
    source_total = at(lot["assigned_factory"]) - qty
    target_total = at(target) + float(lot["consolidated_qty"])
    threshold, hard = cfg["capacity"]["backup_threshold_pct"], cfg["capacity"]["hard_limit_pct"]
    return {
        "valid": True,
        "lot_id": lot_id, "from_factory": lot["assigned_factory"], "to_factory": target,
        "cost_before_usd": float(lot["total_cost_usd"]), "cost_after_usd": float(new_cost),
        "cost_delta_usd": float(new_cost - lot["total_cost_usd"]),
        "cost_multiplier_before": float(lot["cost_multiplier"]), "cost_multiplier_after": mult,
        "lead_time_delta_days": (move["mfg"] + move["trans"]) - (m0 + t0),
        "arrival_before": lot["suggested_rdd"], "arrival_after": arrival,
        "on_time_after": bool(arrival <= lot["earliest_rdd"]),
        "moq_still_met": bool(lot["consolidated_qty"] >= moq),
        "target_load_before_pct": round(move["target_before_pct"], 1),
        "target_utilization_pct": round(move["target_after_pct"], 1),
        "source_load_before_pct": round(move["source_before_pct"], 1),
        "source_load_after_pct": round(move["source_after_pct"], 1),
        "capacity_warning": bool(move["target_after_pct"] >= threshold),
        "over_capacity": bool(move["target_after_pct"] > hard),
        "mpq": mpq,
        "source_total_after": source_total, "target_total_after": target_total,
        "mpq_source_ok": bool(source_total == 0 or source_total >= mpq),
        "mpq_target_ok": bool(target_total >= mpq),
        "decision_type": "manual",
    }
