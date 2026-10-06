"""What-if scenarios (spec section 5, Lusi's slide 6).

Each scenario works on a copy of one run's plan and never changes the baseline.
Every changed lot is marked decision_type = "manual".
"""
import pandas as pd

from engine.planner import Planner
from engine.rules.quantities import pick_to_fill


def _run_lots(planner: Planner, run_id: str) -> pd.DataFrame:
    return planner.run_result(run_id).lots.copy()


def _future_candidates(planner: Planner, run_id: str, article: str, market: str) -> pd.DataFrame:
    open_ids = planner.results[run_id].open_prs
    f = planner.prs.loc[open_ids] if open_ids else planner.prs.iloc[0:0]
    return f[(f["article_id"] == article) & (f["market_destination"] == market)].sort_values("rdd_original")


def check_minimums(planner: Planner, run_id: str, lots: pd.DataFrame, qty_col: str) -> pd.DataFrame:
    """Scenario 2: MOQ cascade. Flags lots that fall below MOQ and proposes a same-market fix."""
    moq = planner.cfg["quantities"]["moq_per_market"]
    rows = []
    for lot in lots.itertuples():
        qty = getattr(lot, qty_col)
        if qty == 0:
            rows.append({"lot_id": lot.lot_id, "moq_ok": True, "fix": "Lot fully held: no units left to buy",
                         "qty_after_fix": 0, "suggested_rdd_after_fix": None})
            continue
        if qty >= moq:
            rows.append({"lot_id": lot.lot_id, "moq_ok": True, "fix": None,
                         "qty_after_fix": qty, "suggested_rdd_after_fix": lot.suggested_rdd})
            continue
        c = _future_candidates(planner, run_id, lot.article_id, lot.market_destination)
        picked = pick_to_fill(moq - qty, list(zip(c["pr_id"], c["requested_qty"])))
        if picked:
            added = c.set_index("pr_id").loc[picked]
            fix = (f"Pull {added['requested_qty'].sum():.0f} units forward from {len(picked)} future "
                   f"{lot.market_destination} requisition(s) of {lot.article_id}")
            rows.append({"lot_id": lot.lot_id, "moq_ok": False, "fix": fix,
                         "qty_after_fix": qty + added["requested_qty"].sum(),
                         "suggested_rdd_after_fix": max(lot.suggested_rdd, added["rdd_original"].max())})
        else:
            rows.append({"lot_id": lot.lot_id, "moq_ok": False,
                         "fix": "No same-market future demand to pull; hold for next window or accept below MOQ",
                         "qty_after_fix": qty, "suggested_rdd_after_fix": lot.suggested_rdd})
    return pd.DataFrame(rows)


def hold_customer(planner: Planner, run_id: str, customer_id: str) -> dict:
    """Scenario 1: put a customer on hold, remove their units, compute NSV at risk."""
    lots = _run_lots(planner, run_id)
    prs = planner.prs
    rows, sizes = [], []
    for lot in lots.itertuples():
        ids = lot.pr_ids.split(",")
        held = prs.loc[ids][prs.loc[ids, "customer_id"] == customer_id]
        if held.empty:
            continue
        removed = float(held["requested_qty"].sum())
        rows.append({"lot_id": lot.lot_id, "article_id": lot.article_id,
                     "market_destination": lot.market_destination,
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
    minimums = check_minimums(planner, run_id, affected, "qty_after")
    affected = affected.merge(minimums, on="lot_id")
    return {
        "customer_id": customer_id,
        "lots_affected": len(affected),
        "nsv_at_risk_usd": float(affected["nsv_at_risk_usd"].sum()),
        "lots": affected,
        "sizes": pd.DataFrame(sizes),
        "moq_alerts": affected[~affected["moq_ok"]],
    }


def delay_factory(planner: Planner, run_id: str, factory: str, days: int) -> dict:
    """Scenario 3: shift the last production date at a factory by N days."""
    lots = _run_lots(planner, run_id)
    lots = lots[lots["assigned_factory"] == factory]
    prs = planner.prs
    rows, late_prs = [], []
    for lot in lots.itertuples():
        new_arrival = lot.expected_arrival + pd.Timedelta(days=days)
        p = prs.loc[lot.pr_ids.split(",")]
        late = p[p["rdd_original"] < new_arrival]
        rows.append({"lot_id": lot.lot_id, "article_id": lot.article_id,
                     "market_destination": lot.market_destination, "qty": lot.consolidated_qty,
                     "rdd": lot.earliest_rdd, "arrival_before": lot.expected_arrival,
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
    """Scenario 3b: manually move a lot to another factory; validate and show the deltas."""
    lots = _run_lots(planner, run_id).set_index("lot_id")
    lot = lots.loc[lot_id]
    if target not in planner.certified[lot["article_id"]]:
        return {"valid": False,
                "message": f"{target} is not certified for {lot['article_id']} (certification matrix)"}
    ids = lot["pr_ids"].split(",")
    po = pd.Timestamp(planner.runs.set_index("run_id").loc[run_id, "po_execution_date"])
    m, t = planner.lot_lead_times(ids, target)
    release = lot["earliest_rdd"] - pd.Timedelta(days=m + t)
    start = max(release, po)
    arrival = start + pd.Timedelta(days=m + t)
    mult = float(planner.factories.loc[target, "cost_multiplier"])
    new_cost = lot["consolidated_qty"] * lot["unit_cost_usd"] * mult
    m0, t0 = planner.lot_lead_times(ids, lot["assigned_factory"])
    ledger = planner.snapshots[run_id]
    util = ledger.utilization(target, ledger.weeks_for(start, m))
    moq = planner.cfg["quantities"]["moq_per_market"]
    return {
        "valid": True,
        "lot_id": lot_id, "from_factory": lot["assigned_factory"], "to_factory": target,
        "cost_before_usd": float(lot["total_cost_usd"]), "cost_after_usd": float(new_cost),
        "cost_delta_usd": float(new_cost - lot["total_cost_usd"]),
        "cost_multiplier_before": float(lot["cost_multiplier"]), "cost_multiplier_after": mult,
        "lead_time_delta_days": (m + t) - (m0 + t0),
        "arrival_before": lot["expected_arrival"], "arrival_after": arrival,
        "on_time_after": bool(arrival <= lot["earliest_rdd"]),
        "moq_still_met": bool(lot["consolidated_qty"] >= moq),
        "target_utilization_pct": float(util),
        "capacity_warning": util >= planner.cfg["capacity"]["backup_threshold_pct"],
        "decision_type": "manual",
    }
