"""Validation checks for the plan's agreed success criteria.

- Complete accounting: every requisition seen has exactly one outcome; units add up.
- Valid recommendations: every bought lot passes the business rules (or carries a warning).
- Capacity: no factory week is loaded beyond the hard limit except by labelled last-chance lots.
- Monthly buying: purchases are only committed in buying runs.
"""
import pandas as pd

from engine.capacity import CapacityLedger
from engine.planner import BOUGHT, PLANNER_REVIEW, Planner


def overload_without_last_chance(planner: Planner) -> float:
    """Highest weekly load (%) from bought lots, leaving out last-chance lots."""
    lots = planner.bought_lots()
    ledger = CapacityLedger(planner.factories["weekly_capacity_units"].to_dict(),
                            planner.cfg["capacity"]["spread_over_manufacturing"])
    for lot in lots[~lots["last_chance"]].itertuples():
        ledger.add(lot.assigned_factory, lot.production_start, lot.mfg_days, lot.consolidated_qty)
    t = ledger.table()
    return float(t["utilization_pct"].max()) if len(t) else 0.0


def accounting_report(planner: Planner) -> dict:
    out = planner.pr_outcomes()
    seen = planner.prs[planner.prs["run_num"] <= planner.processed]
    lots = planner.all_lots()

    in_lots = (lots["pr_ids"].str.split(",").explode() if len(lots) else pd.Series(dtype=str))
    ids_of = lambda d: set(lots.loc[lots["auto_decision"] == d, "pr_ids"].str.split(",").explode()) if len(lots) else set()
    hard = planner.cfg["capacity"]["hard_limit_pct"]
    units_by_outcome = out.groupby("outcome")["requested_qty"].sum().to_dict()
    checks = {
        "every_pr_has_one_outcome": set(out["pr_id"]) == set(seen["pr_id"]) and out["pr_id"].is_unique,
        "no_pr_in_two_lots": in_lots.is_unique,
        "bought_prs_match_lots": ids_of("Buy") == set(out.loc[out["outcome"] == BOUGHT, "pr_id"]),
        "review_prs_match_lots": ids_of("Review") == set(out.loc[out["outcome"] == PLANNER_REVIEW, "pr_id"]),
        "purchases_only_in_buying_windows": set(lots["run_id"]) <= set(planner.buying_runs()) if len(lots) else True,
        "no_overload_except_last_chance": overload_without_last_chance(planner) <= hard + 1e-6,
        "units_add_up": abs(out["requested_qty"].sum() - seen["requested_qty"].sum()) < 1e-6,
        "lot_qty_matches_prs": bool(len(lots) == 0 or (
            lots["consolidated_qty"]
            == lots["pr_ids"].map(lambda s: planner.prs.loc[s.split(","), "requested_qty"].sum())).all()),
    }
    checks = {k: bool(v) for k, v in checks.items()}
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "prs_seen": len(seen),
        "units_seen": float(seen["requested_qty"].sum()),
        "prs_by_outcome": out["outcome"].value_counts().to_dict(),
        "units_by_outcome": {k: float(v) for k, v in units_by_outcome.items()},
    }


def rule_violations(planner: Planner) -> pd.DataFrame:
    """Lots that break a rule without an explicit warning. Should always be empty."""
    lots = planner.bought_lots()
    if lots.empty:
        return lots
    moq = planner.cfg["quantities"]["moq_per_market"]
    rows = []
    for lot in lots.itertuples():
        prs = planner.prs.loc[lot.pr_ids.split(",")]
        if lot.assigned_factory not in planner.certified[lot.article_id]:
            rows.append((lot.lot_id, "uncertified factory"))
        if prs["market_destination"].nunique() != 1 or prs["article_id"].nunique() != 1:
            rows.append((lot.lot_id, "mixes markets or articles"))
        if lot.consolidated_qty < moq and "Below MOQ" not in (lot.warnings or ""):
            rows.append((lot.lot_id, "below MOQ without warning"))
        span = (prs["rdd_original"].max() - prs["rdd_original"].min()).days
        if span > planner.cfg["grouping"]["window_days"] and not lot.is_piggyback_applied:
            rows.append((lot.lot_id, f"RDD span {span} days exceeds grouping window"))
    return pd.DataFrame(rows, columns=["lot_id", "violation"])
