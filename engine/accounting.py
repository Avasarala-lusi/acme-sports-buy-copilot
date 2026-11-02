"""Validation checks for the plan's agreed success criteria.

- Complete accounting: every requisition seen has exactly one outcome; units add up.
- Valid recommendations: every bought lot passes the business rules (or carries a warning).
- Capacity: every purchased factory/production week respects the hard ceiling.
- Buying windows: purchases are only committed in configured buying runs.
"""
import pandas as pd

from engine.capacity import CapacityLedger
from engine.planner import BOUGHT, PLANNER_REVIEW, Planner


def overload_without_last_chance(planner: Planner) -> float:
    """Highest weekly load from ALL bought lots (legacy function name retained)."""
    lots = planner.bought_lots()
    ledger = CapacityLedger(planner.factories["weekly_capacity_units"].to_dict(),
                            planner.cfg["capacity"]["spread_over_manufacturing"])
    for lot in lots.itertuples():
        ledger.add(lot.assigned_factory, lot.production_start, lot.mfg_days, lot.consolidated_qty)
    t = ledger.table()
    return float(t["utilization_pct"].max()) if len(t) else 0.0


def accounting_report(planner: Planner) -> dict:
    out = planner.pr_outcomes()
    seen = planner.prs[planner.prs["run_num"] <= planner.processed]
    lots = planner.all_lots()

    bought=planner.bought_lots()
    in_lots = (bought["pr_ids"].str.split(",").explode() if len(bought) else pd.Series(dtype=str))
    def ids_of(d):
        if not len(lots): return set()
        decisions=lots["decision"].fillna(lots["auto_decision"]) if "decision" in lots else lots["auto_decision"]
        return set(filter(None,lots.loc[decisions==d,"pr_ids"].str.split(",").explode()))
    hard = planner.cfg["capacity"]["hard_limit_pct"]
    units_by_outcome = out.groupby("outcome")["requested_qty"].sum().to_dict()
    review_ids = set(out.loc[out["outcome"].isin(
        [PLANNER_REVIEW, "UNRESOLVED_MOQ", "UNRESOLVED_MPQ"]), "pr_id"])
    current = planner.results[planner.runs.iloc[planner.processed]["run_id"]]
    current_lots = current.lots
    actionable = set()
    if len(current_lots):
        decision = "decision" if "decision" in current_lots else "auto_decision"
        actionable = set(filter(None, current_lots.loc[current_lots[decision] == "Review", "pr_ids"]
                                .str.split(",").explode()))
    review_visible = (review_ids <= actionable if current.is_buying_run or
                      planner.cfg["buying_window"].get("weekly_drafts", True) else True)
    checks = {
        "every_pr_has_one_outcome": set(out["pr_id"]) == set(seen["pr_id"]) and out["pr_id"].is_unique,
        "no_pr_in_two_lots": in_lots.is_unique,
        "bought_prs_match_lots": ids_of("Buy") == set(out.loc[out["outcome"] == BOUGHT, "pr_id"]),
        "review_prs_visible": review_visible,
        "purchases_only_in_buying_windows": set(lots["run_id"]) <= set(planner.buying_runs()) if len(lots) else True,
        "no_overload": overload_without_last_chance(planner) <= hard + 1e-6,
        "units_add_up": abs(out["requested_qty"].sum() - seen["requested_qty"].sum()) < 1e-6,
        "lot_qty_matches_prs": bool(len(lots) == 0 or (
            lots["consolidated_qty"]
            == lots["pr_ids"].map(lambda s: planner.prs.loc[list(filter(None,s.split(","))), "requested_qty"].sum())).all()),
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
        if span > planner.cfg["grouping"]["window_days"]:
            rows.append((lot.lot_id, f"RDD span {span} days exceeds grouping window"))
        if pd.Timestamp(lot.suggested_rdd) != (pd.Timestamp(lot.production_start)+pd.Timedelta(days=lot.mfg_days+lot.trans_days)).normalize():
            rows.append((lot.lot_id,"suggested_rdd does not match the recommended production/transit schedule"))
    from engine.rules.quantities import mpq_for
    for _,run_lots in lots.groupby("run_id"):
        for band in planner.mpq_groups(run_lots.to_dict("records")):
            minimum=mpq_for(band[0]["category"],planner.cfg["quantities"]["mpq"])
            if sum(r["consolidated_qty"] for r in band)<minimum and not any(r["last_chance"] for r in band):
                rows.extend((r["lot_id"],"MPQ not met within article/factory group") for r in band)
    return pd.DataFrame(rows, columns=["lot_id", "violation"])
