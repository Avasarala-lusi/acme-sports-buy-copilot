"""FastAPI service over the planning engine, used by the web front end.

Run with:  uvicorn api.main:app --reload
If frontend/dist exists (npm run build), the web app is also served at /ui.
"""
import io
import json
import threading
from functools import lru_cache
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine import benchmark, data_health, drill, forecast, impact, pull_forward, risk
from engine.calendar import window_label
from engine.accounting import accounting_report, rule_violations
from engine.metrics import baseline_evaluation, comparison_table
from engine.output import fact_buy_plan_suggestions, get_planner
from engine.overrides import OverrideStore, effective_fact_table, effective_lots, ensure_decidable
from engine.planner import FUTURE_FORECAST, OPEN, PLANNER_REVIEW, UNRESOLVED_MOQ, UNRESOLVED_MPQ
from engine.settings_info import settings_items, thresholds
from sim import scenarios

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="Acme Sports Buy Planner API", version="0.3.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


_planner_lock = threading.Lock()


@lru_cache
def _automatic_planner():
    return get_planner()


def automatic_planner():
    """The planned engine, built once even when the first requests arrive together."""
    with _planner_lock:
        return _automatic_planner()


def planner():
    return store().replay(automatic_planner())


def store() -> OverrideStore:
    return OverrideStore()


def _records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", date_format="iso"))


def _json(obj):
    return json.loads(json.dumps(obj, default=str))


def _check_run(run_id: str):
    if run_id not in planner().run_index:
        raise HTTPException(404, f"unknown run {run_id}")


def _kpis(lots: pd.DataFrame, outcomes: pd.DataFrame) -> dict:
    p = planner()
    decision = "decision" if "decision" in lots else "auto_decision"
    review = lots[lots[decision] == "Review"] if len(lots) else lots
    if len(lots):
        lots = lots[(lots[decision] == "Buy") & (lots["consolidated_qty"] > 0)]
    units = float(lots["consolidated_qty"].sum()) if len(lots) else 0.0
    cost = float(lots["total_cost_usd"].sum()) if len(lots) else 0.0
    on_time = float(lots["on_time_units"].sum()) if len(lots) else 0.0
    qty = lambda kinds: float(p.prs.loc[outcomes.loc[outcomes["outcome"].isin(kinds), "pr_id"], "requested_qty"].sum()) \
        if len(outcomes) else 0.0
    return {
        "lots": int(len(lots)), "units_bought": units, "production_cost_usd": cost,
        "cost_per_unit_usd": cost / units if units else 0.0,
        "units_on_time": on_time, "on_time_pct": on_time / units * 100 if units else 0.0,
        "backup_routed_pct": float((lots["assigned_factory"] != lots["primary_factory"]).mean() * 100) if len(lots) else 0.0,
        "lots_with_warnings": int((lots["warnings"] != "").sum()) if len(lots) else 0,
        "unresolved_units": qty([UNRESOLVED_MOQ, UNRESOLVED_MPQ]),
        "forecast_excluded_units": qty([FUTURE_FORECAST]),
        "review_lots": int(len(review)),
        "review_units": float(review["consolidated_qty"].sum()) if len(review) else 0.0,
    }


def _window_info(run_id: str) -> dict:
    p = planner()
    r = p.run_result(run_id)
    po = pd.to_datetime(p.runs["po_execution_date"]).dt.normalize()
    commit = p.runs.loc[po == r.buy_date, "run_id"]
    return {"is_buying_run": r.is_buying_run, "plan_status": r.plan_status,
            "buying_window": window_label(r.buy_date), "buy_date": r.buy_date.isoformat(),
            "next_buy_date": r.next_buy_date.isoformat(),
            "buying_run_id": commit.iloc[0] if len(commit) else None}


# ------------------------------------------------------------------ reference data
@app.get("/health")
def health():
    return {"status": "ok", "runs": len(planner().runs)}


@app.get("/runs")
def runs():
    cols = ["run_id", "week_number", "mrp_freeze_datetime_utc", "as_is_plan_date", "go_nogo_date",
            "po_execution_date", "factory_transmission_date", "factory_confirm_deadline",
            "season", "range_version", "quarter"]
    p = planner()
    out = p.runs[cols].copy()
    out["is_buying_run"] = out["run_id"].isin(p.buying_runs())
    return _records(out)


@app.get("/factories")
def factories():
    f = planner().factories.reset_index()
    return _records(f[["factory_id", "country", "specialization", "weekly_capacity_units", "cost_multiplier",
                       "backup_factory"]])


@app.get("/settings")
def settings():
    cfg = planner().cfg
    return {"thresholds": thresholds(cfg), "items": settings_items(cfg)}


@app.get("/data-issues")
def data_issues():
    return planner().data.issues


@app.get("/features")
def features():
    return {"forecast": True, "risk": True, "optimizer": True, "drill": True,
            "benchmark": True, "ask": False, "data_health": True}


def _checks():
    p = planner()
    p.plan_all()
    rep = accounting_report(p)
    rep["rule_violations"] = len(rule_violations(p))
    rep["comparison"] = _records(comparison_table(p))
    rep["baseline"] = _records(baseline_evaluation(p))
    return _json(rep)


@app.get("/checks")
def checks():
    return _checks()


# ------------------------------------------------------------------ weekly plan
@app.get("/plan/{run_id}")
def plan(run_id: str):
    _check_run(run_id)
    p, s = planner(), store()
    r = p.run_result(run_id)
    eff = effective_lots(p, run_id, s)
    if len(eff):
        eff["certified_factories"] = eff["article_id"].map(lambda a: sorted(p.certified[a]))
    outcome = r.outcomes["outcome"] if len(r.outcomes) else pd.Series(dtype=str)
    k = _kpis(eff, r.outcomes)
    waiting_units = float(p.prs.loc[r.open_prs, "requested_qty"].sum()) if r.open_prs else 0.0
    return {"run_id": run_id, **_window_info(run_id),
            "kpis": k,
            "kpis_automatic": _kpis(automatic_planner().run_result(run_id).lots,
                                    automatic_planner().run_result(run_id).outcomes),
            "decision_issues": p.decision_issues,
            "units": {"bought": k["units_bought"], "review": k["review_units"], "unresolved": k["unresolved_units"],
                      "future": k["forecast_excluded_units"], "waiting": waiting_units},
            "manual_changes": s.count(run_id),
            "counts": {"unresolved": int(outcome.isin([UNRESOLVED_MOQ, UNRESOLVED_MPQ]).sum()),
                       "future": int((outcome == FUTURE_FORECAST).sum()),
                       "review": int((outcome == PLANNER_REVIEW).sum()),
                       "waiting": len(r.open_prs)},
            "lots": _records(eff)}


def _trend():
    """Automatic-plan KPIs for every buying window, for the trend lines on the buy plan."""
    p = planner()
    rows = []
    for run_id in p.buying_runs():
        r = p.run_result(run_id)
        k = _kpis(r.lots, r.outcomes)
        from engine.calendar import window_label
        rows.append({"run_id": run_id, "buying_window": window_label(r.buy_date), **k})
    return rows


@app.get("/trend")
def trend():
    return _trend()


@app.get("/runs/{run_id}/requisitions")
def run_requisitions(run_id: str, status: str = Query(..., pattern="^(unresolved|future|waiting)$")):
    _check_run(run_id)
    p = planner()
    r = p.run_result(run_id)
    cols = ["pr_id", "article_id", "market_destination", "requested_qty", "rdd_original"]
    if status == "waiting":
        df = p.prs.loc[r.open_prs, cols + ["release_primary"]].reset_index(drop=True) if r.open_prs \
            else pd.DataFrame(columns=cols)
        df["outcome"] = OPEN
        df["reason"] = [p.open_reason(x, run_id) for x in df["pr_id"]] if len(df) else []
        return _records(df)
    kinds = [UNRESOLVED_MOQ, UNRESOLVED_MPQ] if status == "unresolved" else [FUTURE_FORECAST]
    if r.outcomes.empty:
        return []
    out = r.outcomes[r.outcomes["outcome"].isin(kinds)][["pr_id", "outcome", "reason"]]
    return _records(out.merge(p.prs[cols].reset_index(drop=True), on="pr_id"))


@app.get("/runs/{run_id}/customers")
def run_customers(run_id: str):
    _check_run(run_id)
    p = planner()
    lots = p.run_result(run_id).lots
    ids = lots["pr_ids"].str.split(",").explode() if len(lots) else pd.Series(dtype=str, index=[])
    if ids.empty:
        return []
    counts = p.prs.loc[ids, "customer_id"].dropna().value_counts()
    cust = p.data.customers.set_index("customer_id")
    col = lambda c: cust[c] if c in cust else pd.Series(dtype=object)
    return [{"customer_id": c, "name": col("name").get(c), "segment": col("segment").get(c),
             "credit_rating": col("credit_rating").get(c), "n_prs": int(n)} for c, n in counts.items()]


@app.get("/lots/{run_id}/{lot_id}/requisitions")
def lot_requisitions(run_id: str, lot_id: str):
    _check_run(run_id)
    p = planner()
    lots = p.run_result(run_id).lots.set_index("lot_id")
    if lot_id not in lots.index:
        raise HTTPException(404, f"unknown lot {lot_id}")
    ids = list(filter(None,lots.loc[lot_id, "pr_ids"].split(",")))
    out = p.prs.loc[ids, ["pr_id", "size_id", "channel_id", "requested_qty", "rdd_original",
                                    "customer_id", "nsv"]].reset_index(drop=True)
    out["inventory_exposure_days"] = (lots.loc[lot_id,"suggested_rdd"]-out["rdd_original"]).dt.days
    return _records(out)


# ------------------------------------------------------------------ what-if
class Scenario(BaseModel):
    run_id: str
    type: str                      # hold_customer | delay | swap
    customer_id: str | None = None
    factory: str | None = None
    days: int | None = None
    lot_id: str | None = None
    target_factory: str | None = None


@app.post("/scenario")
def scenario(s: Scenario):
    _check_run(s.run_id)
    p = planner()
    if s.type == "hold_customer":
        r = scenarios.hold_customer(p, s.run_id, s.customer_id)
    elif s.type == "delay":
        r = scenarios.delay_factory(p, s.run_id, s.factory, s.days)
    elif s.type == "swap":
        return _json(scenarios.swap_factory(p, s.run_id, s.lot_id, s.target_factory))
    else:
        raise HTTPException(400, f"unknown scenario type {s.type}")
    return {k: _records(v) if isinstance(v, pd.DataFrame) else v for k, v in r.items()}


# ------------------------------------------------------------------ manual decisions
class LotDecision(BaseModel):
    decision: str = "Buy"
    factory: str | None = None
    note: str = ""


class Hold(BaseModel):
    customer_id: str


@app.get("/overrides/{run_id}")
def get_overrides(run_id: str):
    _check_run(run_id)
    return store().data.get(run_id, {"lots": {}, "held_customers": []})


@app.put("/overrides/{run_id}/lots/{lot_id}")
def set_lot_decision(run_id: str, lot_id: str, body: LotDecision):
    _check_run(run_id)
    try:
        store().set_lot(planner(), run_id, lot_id, body.decision, body.factory, body.note)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    return get_overrides(run_id)


@app.delete("/overrides/{run_id}/lots/{lot_id}")
def revert_lot(run_id: str, lot_id: str):
    _check_run(run_id)
    store().revert_lot(run_id, lot_id)
    return get_overrides(run_id)


@app.post("/overrides/{run_id}/holds")
def add_hold(run_id: str, body: Hold):
    _check_run(run_id)
    try:
        ensure_decidable(planner(), run_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    store().hold_customer(run_id, body.customer_id)
    return get_overrides(run_id)


@app.delete("/overrides/{run_id}/holds/{customer_id}")
def remove_hold(run_id: str, customer_id: str):
    _check_run(run_id)
    store().release_customer(run_id, customer_id)
    return get_overrides(run_id)


@app.delete("/overrides/{run_id}")
def revert_week(run_id: str):
    _check_run(run_id)
    store().reset(run_id)
    return get_overrides(run_id)


# ------------------------------------------------------------------ analysis views
def _pull_forward(run_id: str):
    p = planner()
    return {"windows": _records(pull_forward.window_utilization(p, run_id)),
            "recommendations": _records(pull_forward.recommendations(p, run_id))}


@app.get("/pull-forward/{run_id}")
def pull_forward_view(run_id: str):
    _check_run(run_id)
    return _pull_forward(run_id)


class PullDecision(BaseModel):
    pr_ids: list[str]
    target_run_id: str


@app.post("/pull-forward/{run_id}/accept")
def accept_pull_forward(run_id: str, body: PullDecision):
    _check_run(run_id)
    _check_run(body.target_run_id)
    try:
        store().accept_pull(planner(),run_id,body.pr_ids,body.target_run_id)
    except (ValueError,KeyError) as e:
        raise HTTPException(400,str(e))
    return {"scheduled_for":body.target_run_id,"pr_ids":body.pr_ids}


@app.get("/capacity/{run_id}")
def capacity(run_id: str, weeks_before: int = 4, weeks_after: int = 36):
    _check_run(run_id)
    p = planner()
    p.plan_through(run_id)
    t = p.snapshots[run_id].table()
    t["week"] = pd.to_datetime(t["week"])
    start = pd.Timestamp(p.runs.set_index("run_id").loc[run_id, "mrp_freeze_datetime_utc"]).normalize()
    t = t[(t["week"] >= start - pd.Timedelta(weeks=weeks_before)) & (t["week"] <= start + pd.Timedelta(weeks=weeks_after))]
    return _records(t)


@app.get("/network/{run_id}")
def network(run_id: str):
    """Factory -> market routes for the week's lots (after manual decisions), for the network map."""
    _check_run(run_id)
    p, s = planner(), store()
    eff = effective_lots(p, run_id, s)
    eff = eff[eff["consolidated_qty"] > 0] if len(eff) else eff
    routes = []
    if len(eff):
        eff = eff.assign(status=eff["decision"].map(lambda d: "review" if d == "Review" else ("bought" if d == "Buy" else "held")))
        eff = eff[eff["status"] != "held"]
        for (f, m), g in eff.groupby(["assigned_factory", "market_destination"]):
            bought = g[g["status"] == "bought"]
            routes.append({
                "factory_id": f, "market": m, "lots": int(len(g)), "units": float(g["consolidated_qty"].sum()),
                "bought_units": float(bought["consolidated_qty"].sum()),
                "backup_units": float(bought.loc[bought["backup_routed"], "consolidated_qty"].sum()),
                "review_units": float(g.loc[g["status"] == "review", "consolidated_qty"].sum()),
                "cost_usd": float(bought["total_cost_usd"].sum()),
                "on_time_units": float(bought["on_time_units"].sum()),
                "late_lots": int((~bought["on_time"]).sum()),
                "articles": int(g["article_id"].nunique()),
                "max_load_pct": float(g["util_after_pct"].max()),
            })
    fac = p.factories.reset_index()[["factory_id", "country", "weekly_capacity_units", "cost_multiplier"]]
    return {"run_id": run_id, "routes": sorted(routes, key=lambda r: -r["units"]), "factories": _records(fac)}


# ------------------------------------------------------------------ export
@lru_cache(maxsize=64)
def _forecast(run_id: str):
    p = automatic_planner()  # the forecast reads demand and committed load; decisions do not change demand
    intake = forecast.forecast_intake(p, run_id)
    weekly, windows = forecast.forecast_load(p, run_id, intake)
    series = forecast.intake_series(p)
    origin = int(p.runs.set_index("run_id").loc[run_id, "week_number"])
    history = series[series["week"] <= origin][["factory", "week", "date", "units"]]
    return {"run_id": run_id, "origin_week": origin, "model": str(intake["model"].iloc[0]),
            "horizon_weeks": forecast.horizon_weeks(p),
            "stage_coverage_pct": float(intake["has_stage"].mean() * 100),
            "history": _records(history), "intake": _records(intake),
            "load": _records(weekly), "windows": _records(windows)}


@app.get("/forecast/{run_id}")
def forecast_view(run_id: str):
    _check_run(run_id)
    return _forecast(run_id)


_backtest_lock = threading.Lock()


@lru_cache
def _backtest_cached():
    return _json(forecast.cached_backtest(automatic_planner()))


@lru_cache
def _seasonality():
    return _json(forecast.seasonality_tests(automatic_planner()))


@app.get("/forecast-seasonality")
def forecast_seasonality():
    return _seasonality()


@app.get("/forecast-backtest")
def forecast_backtest():
    with _backtest_lock:  # about a minute the first time; never run it twice in parallel
        return _backtest_cached()


@lru_cache(maxsize=8)
def _impact(price: float):
    return _json(impact.impact_report(automatic_planner(), price))  # the automatic plan, as in the evaluation


@app.get("/impact")
def impact_view(price: float = Query(21.0, ge=1, le=1000)):
    """Late and undelivered firm demand, plan vs baseline, by market, product line, channel and customer."""
    return _impact(round(price, 2))


# ------------------------------------------------------------------ extensions
@lru_cache(maxsize=128)
def _risk(run_id: str | None):
    return _json(risk.risk_report(automatic_planner(), run_id))


@app.get("/risk")
def risk_view(run_id: str | None = None):
    """On-time probability of the bought plan (or one buying run) under lead-time variation."""
    if run_id is not None:
        _check_run(run_id)
    return _risk(run_id)


_network_lock = threading.Lock()


@lru_cache
def _network_results():
    return benchmark.cached_network_results(automatic_planner())


@app.get("/network-plans")
def network_plans():
    """Cost/service frontier and planner benchmark (one optimiser solve per weight; a few minutes the first time)."""
    with _network_lock:
        return _network_results()


@lru_cache
def _network_model():
    from engine.optimizer import Network
    return Network(automatic_planner())


class Drill(BaseModel):
    factory: str
    start: str
    end: str
    weight: float = 0.5


@lru_cache(maxsize=16)
def _drill(factory: str, start: str, end: str, weight: float):
    with _network_lock:
        return _json(drill.run_drill(automatic_planner(), factory, start, end, weight, _network_model()))


@app.post("/drill")
def drill_view(d: Drill):
    """Close a factory for a period; compare the rule engine's and the optimiser's response (about a minute)."""
    try:
        return _drill(d.factory, d.start, d.end, round(min(max(d.weight, 0.0), 1.0), 2))
    except ValueError as e:
        raise HTTPException(400, str(e))


@lru_cache(maxsize=128)
def _health(run_id: str | None):
    return _json(data_health.health_report(automatic_planner(), run_id))


@app.get("/data-health")
def data_health_view(run_id: str | None = None):
    """Unusual records in each run's data load, before they affect the plan."""
    if run_id is not None:
        _check_run(run_id)
    return _health(run_id)


@app.get("/export/{run_id}")
def export(run_id: str, format: str = Query("csv", pattern="^(csv|xlsx)$")):
    _check_run(run_id)
    p, s = planner(), store()
    fact = effective_fact_table(p, run_id, s)
    if format == "csv":
        return StreamingResponse(io.StringIO(fact.to_csv(index=False)), media_type="text/csv",
                                 headers={"Content-Disposition": f"attachment; filename=buy_plan_{run_id}.csv"})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        fact.to_excel(xl, sheet_name="buy_plan", index=False)
        effective_lots(p, run_id, s).to_excel(xl, sheet_name="lot_details", index=False)
        p.run_result(run_id).outcomes.to_excel(xl, sheet_name="decisions", index=False)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f"attachment; filename=buy_plan_{run_id}.xlsx"})


@app.get("/export-all")
def export_all():
    csv = fact_buy_plan_suggestions(planner()).to_csv(index=False)
    return StreamingResponse(io.StringIO(csv), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=buy_plan_all_weeks.csv"})


# ------------------------------------------------------------------ web app
DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/ui", StaticFiles(directory=DIST, html=True), name="ui")

    @app.get("/", include_in_schema=False)
    def index():
        return RedirectResponse("/ui/")
