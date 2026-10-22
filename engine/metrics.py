"""KPIs and the comparison against the as-is reference plan.

Client's proposed metrics: production cost, units arriving on time, unresolved demand.
The "as-is" reference uses the factory assignments in the supplied data and buys every
requisition in the run it appears, with no rules applied.
"""
import pandas as pd

from engine.planner import FUTURE_FORECAST, OPEN, PLANNER_REVIEW, UNRESOLVED_MOQ, UNRESOLVED_MPQ, Planner


def as_is_plan(planner: Planner, run_ids: list[str] | None = None) -> pd.DataFrame:
    prs = planner.prs
    if run_ids is not None:
        prs = prs[prs["run_id"].isin(run_ids)]
    runs = planner.runs.set_index("run_id")
    mult = planner.factories["cost_multiplier"]
    po = prs["run_id"].map(runs["po_execution_date"])
    release = prs["rdd_original"] - pd.to_timedelta(
        prs["manufacturing_lead_time"] + prs["transportation_lead_time"], unit="D")
    start = pd.concat([release, po], axis=1).max(axis=1)
    arrival = start + pd.to_timedelta(prs["manufacturing_lead_time"] + prs["transportation_lead_time"], unit="D")
    out = prs[["pr_id", "run_id", "article_id", "market_destination", "requested_qty",
               "rdd_original", "assigned_factory", "backup_triggered", "unit_cost_usd"]].copy()
    out["cost_usd"] = out["requested_qty"] * out["unit_cost_usd"] * out["assigned_factory"].map(mult)
    out["suggested_rdd"] = arrival
    out["on_time"] = arrival <= out["rdd_original"]
    return out.reset_index(drop=True)


def plan_kpis(planner: Planner, run_ids: list[str] | None = None) -> dict:
    lots = planner.bought_lots()
    out = planner.pr_outcomes()
    if run_ids is not None:
        lots = lots[lots["run_id"].isin(run_ids)]
        out = out[out["run_id"].isin(run_ids)]
    bought_units = float(lots["consolidated_qty"].sum()) if len(lots) else 0.0
    units = lambda o: float(out.loc[out["outcome"] == o, "requested_qty"].sum())
    return {
        "lots": len(lots),
        "units_bought": bought_units,
        "production_cost_usd": float(lots["total_cost_usd"].sum()) if len(lots) else 0.0,
        "cost_per_unit_usd": float(lots["total_cost_usd"].sum() / bought_units) if bought_units else 0.0,
        "units_on_time": float(lots["on_time_units"].sum()) if len(lots) else 0.0,
        "on_time_pct": float(lots["on_time_units"].sum() / bought_units * 100) if bought_units else 0.0,
        "backup_routed_pct": float(lots["backup_routed"].mean() * 100) if len(lots) else 0.0,
        "lots_with_warnings": int((lots["warnings"] != "").sum()) if len(lots) else 0,
        "unresolved_units": units(UNRESOLVED_MOQ) + units(UNRESOLVED_MPQ),
        "review_units": units(PLANNER_REVIEW),
        "forecast_excluded_units": units(FUTURE_FORECAST),
        "open_units": units(OPEN),
    }


def as_is_kpis(planner: Planner, run_ids: list[str] | None = None) -> dict:
    a = as_is_plan(planner, run_ids)
    moq = planner.cfg["quantities"]["moq_per_market"]
    per_lot = a.groupby(["run_id", "article_id", "market_destination"])["requested_qty"].sum()
    units = float(a["requested_qty"].sum())
    return {
        "lots": int(len(per_lot)),
        "units_bought": units,
        "production_cost_usd": float(a["cost_usd"].sum()),
        "cost_per_unit_usd": float(a["cost_usd"].sum() / units) if units else 0.0,
        "units_on_time": float(a.loc[a["on_time"], "requested_qty"].sum()),
        "on_time_pct": float(a.loc[a["on_time"], "requested_qty"].sum() / units * 100) if units else 0.0,
        "backup_routed_pct": float(a["backup_triggered"].mean() * 100),
        "lots_below_moq": int((per_lot < moq).sum()),
        "unresolved_units": 0.0,
        "review_units": 0.0,
    }


def comparison_table(planner: Planner, run_ids: list[str] | None = None) -> pd.DataFrame:
    ours, ref = plan_kpis(planner, run_ids), as_is_kpis(planner, run_ids)
    keys = ["units_bought", "production_cost_usd", "cost_per_unit_usd", "units_on_time",
            "on_time_pct", "backup_routed_pct", "unresolved_units", "review_units"]
    return pd.DataFrame({"metric": keys, "our_plan": [ours[k] for k in keys],
                         "as_is_reference": [ref[k] for k in keys]})
