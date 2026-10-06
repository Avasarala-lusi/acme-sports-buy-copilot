"""Capacity-driven pull-forward analysis (spec section 3.3).

For a run, project each factory's load over the next buying windows using our own
committed assignments plus the open demand not yet bought. Where a future window is
projected at or above the threshold, recommend pulling that demand into an earlier,
lower-load window, checked per market against MOQ, and show the cost of the
alternative (routing to the backup factory in the overloaded window).
"""
from datetime import timedelta

import pandas as pd

from engine.calendar import _add_months, window_cutoff, window_label
from engine.planner import Planner


def _windows(run_date, cutoff_day: int, n: int) -> list:
    first = window_cutoff(run_date, cutoff_day)
    return [_add_months(first, i) for i in range(n + 1)]


def projected_load(planner: Planner, run_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Weekly load per factory: committed (ledger) + projected open demand at its primary factory."""
    planner.plan_through(run_id)
    ledger = planner.snapshots[run_id].copy()
    committed = ledger.table().assign(kind="committed")
    open_ids = planner.results[run_id].open_prs
    opn = planner.prs.loc[open_ids] if open_ids else planner.prs.iloc[0:0]
    for pr in opn.itertuples():
        m, _ = planner.lead_times(planner.prs.loc[pr.pr_id], pr.primary)
        ledger.add(pr.primary, pr.release_primary, m, pr.requested_qty)
    return ledger.table(), opn


def window_utilization(planner: Planner, run_id: str) -> pd.DataFrame:
    cfg = planner.cfg["buying_window"]
    run_date = planner.runs.set_index("run_id").loc[run_id, "mrp_freeze_datetime_utc"]
    edges = _windows(run_date, cfg["cutoff_day"], cfg["lookahead_windows"])
    load, _ = projected_load(planner, run_id)
    rows = []
    for i in range(len(edges) - 1):
        lo, hi = pd.Timestamp(edges[i]), pd.Timestamp(edges[i + 1])
        weeks = pd.date_range(lo - timedelta(days=lo.weekday()), hi, freq="W-MON")
        for f, cap in planner.factories["weekly_capacity_units"].items():
            sel = load[(load["factory_id"] == f) & load["week"].map(pd.Timestamp).between(lo, hi, inclusive="left")]
            units = float(sel["units"].sum())
            rows.append({"window": window_label(edges[i]), "window_start": lo, "factory_id": f,
                         "units": units, "avg_utilization_pct": units / (cap * max(len(weeks), 1)) * 100})
    return pd.DataFrame(rows)


def recommendations(planner: Planner, run_id: str) -> pd.DataFrame:
    cfg = planner.cfg
    threshold = cfg["capacity"]["backup_threshold_pct"]
    moq = cfg["quantities"]["moq_per_market"]
    util = window_utilization(planner, run_id)
    _, opn = projected_load(planner, run_id)
    if opn.empty:
        return pd.DataFrame()
    run_lots = planner.results[run_id].lots
    current_qty = (run_lots.groupby(["article_id", "market_destination"])["consolidated_qty"].sum()
                   if len(run_lots) else pd.Series(dtype=float))
    windows = sorted(util["window_start"].unique())
    mult = planner.factories["cost_multiplier"]
    rows = []
    for f in planner.factories.index:
        fu = util[util["factory_id"] == f].set_index("window_start")["avg_utilization_pct"]
        for i, w in enumerate(windows[1:], start=1):
            if fu.get(w, 0) < threshold:
                continue
            earlier = [x for x in windows[:i] if fu.get(x, 0) < threshold]
            hi = windows[i + 1] if i + 1 < len(windows) else pd.Timestamp(w) + pd.DateOffset(months=1)
            sel = opn[(opn["primary"] == f) & (opn["release_primary"] >= w) & (opn["release_primary"] < hi)]
            for (article, market), g in sel.groupby(["article_id", "market_destination"]):
                qty = float(g["requested_qty"].sum())
                existing = float(current_qty.get((article, market), 0))
                backup = g["backup"].iloc[0]
                unit_cost = float(g["unit_cost_usd"].iloc[0])
                saving = qty * unit_cost * (float(mult[backup]) - float(mult[f]))
                target = earlier[0] if earlier else None
                rows.append({
                    "factory_id": f, "overloaded_window": window_label(pd.Timestamp(w).date()),
                    "overloaded_util_pct": round(float(fu[w]), 1),
                    "article_id": article, "market_destination": market, "n_prs": len(g), "units": qty,
                    "recommendation": (f"Pull forward to {window_label(pd.Timestamp(target).date())} "
                                       f"({fu[target]:.0f}% load)") if target else
                                      f"No earlier window below {threshold}%: keep, or route to backup {backup}",
                    "target_window": window_label(pd.Timestamp(target).date()) if target else None,
                    "days_earlier": int((g["release_primary"].min() - pd.Timestamp(target)).days) if target else 0,
                    "moq_ok_for_market": qty >= moq or qty + existing >= moq,
                    "backup_factory": backup,
                    "extra_cost_if_routed_to_backup_usd": round(saving, 2),
                })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["actionable"] = out["target_window"].notna() & out["moq_ok_for_market"]
    return (out.sort_values(["actionable", "extra_cost_if_routed_to_backup_usd"], ascending=[False, False])
               .reset_index(drop=True))
