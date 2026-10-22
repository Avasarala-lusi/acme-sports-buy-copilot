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


def baseline_evaluation(planner: Planner) -> pd.DataFrame:
    """Client (Oct 2026): evaluate against the baseline in fact_purchase_requisitions (assigned_factory,
    backup_triggered) on the same requisitions and the same demand volume.

    'Same requisitions' are the ones our plan buys. The baseline places each at its supplied factory with its own
    lead times, starting on the PO date of the run it appeared in; our plan places it where and when our lot does.
    """
    import numpy as np

    from engine.capacity import CapacityLedger
    from engine.planner import BOUGHT

    lots = planner.bought_lots()
    if lots.empty:
        return pd.DataFrame()
    moq = planner.cfg["quantities"]["moq_per_market"]
    caps = planner.factories["weekly_capacity_units"].to_dict()
    mult = planner.factories["cost_multiplier"]
    c = planner.cfg["capacity"]

    ours = lots.assign(pr_id=lots["pr_ids"].str.split(",")).explode("pr_id")
    out = planner.pr_outcomes().set_index("pr_id")
    ids = ours.loc[ours["pr_id"].map(out["outcome"]) == BOUGHT, "pr_id"]
    prs = planner.prs.loc[ids]
    po = prs["run_id"].map(planner.runs.set_index("run_id")["po_execution_date"]).map(pd.Timestamp)
    lt = prs["manufacturing_lead_time"] + prs["transportation_lead_time"]
    release = prs["rdd_original"] - pd.to_timedelta(lt, unit="D")
    base_start = list(po)  # client: production starts on the PO execution date
    base_arrival = pd.Series(base_start, index=prs.index) + pd.to_timedelta(lt, unit="D")

    def spread(ledger):
        t = ledger.table()
        if t.empty:
            return 0.0, 0.0, 0
        grid = t.pivot_table(index="week", columns="factory_id", values="utilization_pct", aggfunc="sum").reindex(
            columns=list(caps)).fillna(0.0)
        return float(grid.std(axis=1).mean()), float(grid.max(axis=1).mean()), int((grid > c["hard_limit_pct"] + 1e-6).sum().sum())

    base_ledger = CapacityLedger(caps, c["spread_over_manufacturing"])
    for pr, s in zip(prs.itertuples(), base_start):
        base_ledger.add(pr.assigned_factory, s, pr.manufacturing_lead_time, pr.requested_qty)
    our_ledger = CapacityLedger(caps, c["spread_over_manufacturing"])
    for lot in lots.itertuples():
        our_ledger.add(lot.assigned_factory, lot.production_start, lot.mfg_days, lot.consolidated_qty)
    b_std, b_peak, b_over = spread(base_ledger)
    o_std, o_peak, o_over = spread(our_ledger)

    units = float(prs["requested_qty"].sum())
    base_lots = prs.groupby(["run_id", "article_id", "market_destination"])["requested_qty"].sum()
    base_cost = float((prs["requested_qty"] * prs["unit_cost_usd"] * prs["assigned_factory"].map(mult)).sum())
    base_on_time = float(prs.loc[base_arrival <= prs["rdd_original"], "requested_qty"].sum())
    our_backup = (ours.set_index("pr_id").loc[ids, "assigned_factory"] != prs["primary"]).mean()

    rows = [
        ("Requisitions compared (same PRs, same units)", len(prs), len(prs), None, f"{units:,.0f} units"),
        ("Backup-triggered assignments (% of PRs)", prs["backup_triggered"].mean() * 100, our_backup * 100, "lower",
         "Did the engine reduce backup-triggered assignments?"),
        ("Load spread across factories (avg weekly std, pts)", b_std, o_std, "lower",
         "Did the engine lower utilisation variance across factories?"),
        ("Busiest factory each week (avg %)", b_peak, o_peak, "lower", "Average of each week's highest factory load"),
        ("Factory-weeks above 100%", b_over, o_over, "lower", "Hard ceiling"),
        ("Article-market lots below MOQ 300 (%)", (base_lots < moq).mean() * 100, (lots["consolidated_qty"] < moq).mean() * 100,
         "lower", "Did the engine better protect MOQ per market?"),
        ("Article-market lots", len(base_lots), len(lots), None, "Baseline buys each PR in the run it appears"),
        ("Production cost ($M)", base_cost / 1e6, float(lots["total_cost_usd"].sum()) / 1e6, "lower", ""),
        ("Units on time (%)", base_on_time / units * 100, float(lots["on_time_units"].sum()) / units * 100, "higher", ""),
    ]
    df = pd.DataFrame(rows, columns=["metric", "baseline", "our_plan", "better_if", "note"])
    df["improved"] = [None if b is None else (o < bl if b == "lower" else o > bl)
                      for bl, o, b in zip(df["baseline"], df["our_plan"], df["better_if"])]
    return df.replace({np.nan: None})
