"""Capacity-driven pull-forward analysis (spec section 3.3).

For a run, project each factory's weekly load over the next buying windows: the run's capacity
ledger (committed lots, plus the run's draft lots in a draft week) and the open demand not yet bought,
placed at its primary factory. A window is overloaded when its busiest week reaches the threshold,
because a monthly average can hide a single overloaded week.

For each overloaded window, open demand is moved one article-market group at a time (largest first)
into the closest earlier window that can take it. Every move is tested on a working copy of the ledger
that already holds the moves accepted before it, so recommendations never claim the same capacity, and
a move is accepted only if:
  - every week the moved demand occupies, and the target window's busiest week, stay below the threshold,
  - the market still reaches MOQ in the target window,
  - the article reaches MPQ at the factory in the target window, and
  - what stays behind in the overloaded window is zero or still reaches MPQ.
Moves stop once the overloaded window is back below the threshold.
"""
from collections import defaultdict

import pandas as pd

from engine.calendar import weeks_between, window_label
from engine.capacity import CapacityLedger
from engine.planner import Planner
from engine.rules.quantities import mpq_for


def _edges(planner: Planner, run_id: str) -> list[pd.Timestamp]:
    """Window start dates: the run's window, the next lookahead windows, and one more as the end."""
    r = planner.run_result(run_id)
    n = planner.cfg["buying_window"]["lookahead_windows"]
    return [pd.Timestamp(d) for d in planner.calendar.windows_from(r.buy_date, n + 1)]


def _window_index(edges: list[pd.Timestamp], d) -> int | None:
    d = pd.Timestamp(d)
    for i in range(len(edges) - 1):
        if edges[i] <= d < edges[i + 1]:
            return i
    return None


def window_stats(ledger: CapacityLedger, factory: str, weeks: list) -> dict:
    """Load of a factory over a window. Numerator and denominator use exactly the same weeks."""
    cap = ledger.capacity[factory]
    units = [ledger.units[factory].get(w, 0.0) for w in weeks]
    if not weeks:
        return {"units": 0.0, "weeks": 0, "avg_pct": 0.0, "peak_pct": 0.0}
    return {"units": float(sum(units)), "weeks": len(weeks),
            "avg_pct": float(sum(units) / (cap * len(weeks)) * 100),
            "peak_pct": float(max(units) / cap * 100)}


def projected_load(planner: Planner, run_id: str) -> tuple[CapacityLedger, pd.DataFrame]:
    """The run's ledger plus open demand at its primary factory, and the open demand placed."""
    planner.plan_through(run_id)
    r = planner.run_result(run_id)
    ledger = planner.snapshots[run_id].copy()
    open_ids = r.open_prs
    opn = planner.prs.loc[open_ids].copy() if open_ids else planner.prs.iloc[0:0].copy()
    starts, mfgs = [], []
    for pr in opn.itertuples():
        m, _ = planner.lead_times(planner.rows[pr.pr_id], pr.primary)
        start = max(pr.release_primary, r.buy_date)
        ledger.add(pr.primary, start, m, pr.requested_qty)
        starts.append(start)
        mfgs.append(m)
    opn["start"], opn["mfg"] = starts, mfgs
    return ledger, opn


def window_utilization(planner: Planner, run_id: str) -> pd.DataFrame:
    edges = _edges(planner, run_id)
    ledger, _ = projected_load(planner, run_id)
    rows = []
    for i in range(len(edges) - 1):
        weeks = weeks_between(edges[i], edges[i + 1])
        for f in planner.factories.index:
            s = window_stats(ledger, f, weeks)
            rows.append({"window": window_label(edges[i]), "window_start": edges[i], "factory_id": f,
                         "units": s["units"], "weeks": s["weeks"],
                         "avg_utilization_pct": s["avg_pct"], "peak_utilization_pct": s["peak_pct"]})
    return pd.DataFrame(rows)


def _committed_quantities(planner: Planner, run_id: str, edges) -> tuple[dict, dict]:
    """Units already planned per (article, market, window) and (article, factory, window)."""
    k = planner.run_index[run_id]
    past = planner.bought_lots()
    if len(past):
        past = past[past["run_id"].map(planner.run_index) < k]
    this = planner.run_result(run_id).lots
    this = this[this["auto_decision"] == "Buy"] if len(this) else this
    lots = pd.concat([x for x in (past, this) if len(x)]) if len(past) or len(this) else past
    by_market, by_factory = defaultdict(float), defaultdict(float)
    for lot in lots.itertuples() if len(lots) else []:
        i = _window_index(edges, lot.production_start)
        if i is not None:
            by_market[(lot.article_id, lot.market_destination, i)] += lot.consolidated_qty
            by_factory[(lot.article_id, lot.assigned_factory, i)] += lot.consolidated_qty
    return by_market, by_factory


def recommendations(planner: Planner, run_id: str) -> pd.DataFrame:
    cfg = planner.cfg
    threshold = cfg["capacity"]["backup_threshold_pct"]
    moq = cfg["quantities"]["moq_per_market"]
    edges = _edges(planner, run_id)
    work, opn = projected_load(planner, run_id)
    if opn.empty:
        return pd.DataFrame()
    opn["window"] = opn["start"].map(lambda d: _window_index(edges, d))
    by_market, by_factory = _committed_quantities(planner, run_id, edges)
    for pr in opn.itertuples():  # open demand is planned too: it counts towards the minimums
        if pr.window is not None:
            by_market[(pr.article_id, pr.market_destination, pr.window)] += pr.requested_qty
            by_factory[(pr.article_id, pr.primary, pr.window)] += pr.requested_qty
    mult = planner.factories["cost_multiplier"]
    windows = [weeks_between(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]

    rows = []
    for f in planner.factories.index:
        for i in range(1, len(windows)):
            if window_stats(work, f, windows[i])["peak_pct"] < threshold:
                continue
            sel = opn[(opn["primary"] == f) & (opn["window"] == i)]
            groups = sorted(sel.groupby(["article_id", "market_destination"]),
                            key=lambda kv: -kv[1]["requested_qty"].sum())
            for (article, market), g in groups:
                source_peak = window_stats(work, f, windows[i])["peak_pct"]
                if source_peak < threshold:
                    break  # the window is relieved by the moves already accepted
                qty = float(g["requested_qty"].sum())
                mpq = mpq_for(g["category"].iloc[0], cfg["quantities"]["mpq"])
                left_behind = by_factory[(article, f, i)] - qty
                mpq_source_ok = left_behind <= 1e-9 or left_behind >= mpq
                backup = g["backup"].iloc[0]
                backup = backup if isinstance(backup, str) else None  # the last resort has no backup
                row = {
                    "factory_id": f, "overloaded_window": window_label(edges[i]),
                    "overloaded_util_pct": round(source_peak, 1),
                    "article_id": article, "market_destination": market, "n_prs": len(g), "units": qty,
                    "target_window": None, "days_earlier": 0,
                    "capacity_ok": False, "moq_ok_for_market": False, "mpq_target_ok": False,
                    "mpq_source_ok": bool(mpq_source_ok),
                    "source_peak_after_pct": round(source_peak, 1),
                    "target_peak_before_pct": None, "target_peak_after_pct": None,
                    "backup_factory": backup,
                    "extra_cost_if_routed_to_backup_usd": round(
                        qty * float(g["unit_cost_usd"].iloc[0]) * (float(mult[backup]) - float(mult[f])), 2) if backup else None,
                }
                why_not = []
                for j in range(i - 1, -1, -1):  # closest earlier window first
                    trial = work.copy()
                    moved_weeks = set()
                    for pr in g.itertuples():
                        trial.remove(f, pr.start, pr.mfg, pr.requested_qty)
                        trial.add(f, edges[j], pr.mfg, pr.requested_qty)
                        moved_weeks.update(trial.weeks_for(edges[j], pr.mfg))
                    peak_moved = max(trial.units[f][w] / trial.capacity[f] * 100 for w in moved_weeks)
                    capacity_ok = (peak_moved < threshold
                                   and window_stats(trial, f, windows[j])["peak_pct"] < threshold)
                    moq_ok = by_market[(article, market, j)] + qty >= moq
                    mpq_ok = by_factory[(article, f, j)] + qty >= mpq
                    checks = {"capacity": capacity_ok, "market MOQ": moq_ok, "factory MPQ": mpq_ok,
                              "MPQ left in the overloaded window": mpq_source_ok}
                    if all(checks.values()):
                        target_before = window_stats(work, f, windows[j])["peak_pct"]
                        work = trial
                        by_factory[(article, f, i)] -= qty
                        by_factory[(article, f, j)] += qty
                        by_market[(article, market, i)] -= qty
                        by_market[(article, market, j)] += qty
                        row.update(target_window=window_label(edges[j]),
                                   days_earlier=int((g["start"].min() - edges[j]).days),
                                   capacity_ok=True, moq_ok_for_market=True, mpq_target_ok=True,
                                   source_peak_after_pct=round(window_stats(work, f, windows[i])["peak_pct"], 1),
                                   target_peak_before_pct=round(target_before, 1),
                                   target_peak_after_pct=round(window_stats(work, f, windows[j])["peak_pct"], 1))
                        break
                    if j == i - 1:  # report the checks of the closest window
                        row.update(capacity_ok=capacity_ok, moq_ok_for_market=moq_ok, mpq_target_ok=mpq_ok)
                    why_not.append(f"{window_label(edges[j])}: " + ", ".join(k for k, ok in checks.items() if not ok))
                if row["target_window"]:
                    row["recommendation"] = (
                        f"Pull forward to {row['target_window']}: busiest week there "
                        f"{row['target_peak_before_pct']:.1f}% → {row['target_peak_after_pct']:.1f}%; "
                        f"{row['overloaded_window']} {row['overloaded_util_pct']:.1f}% → {row['source_peak_after_pct']:.1f}%")
                else:
                    row["recommendation"] = ("No earlier window can take it (" + "; ".join(why_not or ["none open"])
                                             + (f"). Keep, or route to backup {backup}" if backup
                                                else f"). {f} is the last resort: keep, or review with the planner"))
                rows.append(row)
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["actionable"] = out["target_window"].notna()
    return (out.sort_values(["actionable", "units"], ascending=[False, False]).reset_index(drop=True))
