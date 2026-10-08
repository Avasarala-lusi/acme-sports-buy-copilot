"""FastAPI service over the planning engine, used by the web front end.

Run with:  uvicorn api.main:app --reload
If frontend/dist exists (npm run build), the web app is also served at /ui.
"""
import io
import json
from functools import lru_cache
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine import pull_forward
from engine.accounting import accounting_report, rule_violations
from engine.metrics import comparison_table
from engine.output import fact_buy_plan_suggestions, get_planner
from engine.overrides import DECISIONS, OverrideStore, effective_fact_table, effective_lots
from engine.planner import FUTURE_FORECAST, OPEN, UNRESOLVED_MOQ, UNRESOLVED_MPQ
from engine.settings_info import settings_items, thresholds
from sim import scenarios

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="Acme Sports Buy Planner API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


@lru_cache
def planner():
    return get_planner()


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
    if "decision" in lots:
        lots = lots[(lots["decision"] == "Buy") & (lots["consolidated_qty"] > 0)]
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
    }


# ------------------------------------------------------------------ reference data
@app.get("/health")
def health():
    return {"status": "ok", "runs": len(planner().runs)}


@app.get("/runs")
def runs():
    cols = ["run_id", "week_number", "mrp_freeze_datetime_utc", "as_is_plan_date", "go_nogo_date",
            "po_execution_date", "factory_transmission_date", "factory_confirm_deadline",
            "season", "range_version", "quarter"]
    return _records(planner().runs[cols])


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
    return {"forecast": False, "risk": False, "optimizer": False, "drill": False,
            "benchmark": False, "ask": False, "data_health": False}


@lru_cache
def _checks():
    p = planner()
    rep = accounting_report(p)
    rep["rule_violations"] = len(rule_violations(p))
    rep["comparison"] = _records(comparison_table(p))
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
    eff["certified_factories"] = eff["article_id"].map(lambda a: sorted(p.certified[a]))
    return {"run_id": run_id,
            "kpis": _kpis(eff, r.outcomes),
            "kpis_automatic": _kpis(r.lots, r.outcomes),
            "manual_changes": s.count(run_id),
            "counts": {"unresolved": int(r.outcomes["outcome"].isin([UNRESOLVED_MOQ, UNRESOLVED_MPQ]).sum()),
                       "future": int((r.outcomes["outcome"] == FUTURE_FORECAST).sum()),
                       "waiting": len(r.open_prs)},
            "lots": _records(eff)}


@app.get("/runs/{run_id}/requisitions")
def run_requisitions(run_id: str, status: str = Query(..., pattern="^(unresolved|future|waiting)$")):
    _check_run(run_id)
    p = planner()
    r = p.run_result(run_id)
    cols = ["pr_id", "article_id", "market_destination", "requested_qty", "rdd_original"]
    if status == "waiting":
        df = p.prs.loc[r.open_prs, cols + ["release_primary"]].reset_index(drop=True) if r.open_prs \
            else pd.DataFrame(columns=cols)
        df["outcome"], df["reason"] = OPEN, "Not yet due; carried to later runs"
        return _records(df)
    kinds = [UNRESOLVED_MOQ, UNRESOLVED_MPQ] if status == "unresolved" else [FUTURE_FORECAST]
    out = r.outcomes[r.outcomes["outcome"].isin(kinds)][["pr_id", "outcome", "reason"]]
    return _records(out.merge(p.prs[cols].reset_index(drop=True), on="pr_id"))


@app.get("/runs/{run_id}/customers")
def run_customers(run_id: str):
    _check_run(run_id)
    p = planner()
    lots = p.run_result(run_id).lots
    ids = lots["pr_ids"].str.split(",").explode() if len(lots) else pd.Series(dtype=str)
    counts = p.prs.loc[ids, "customer_id"].dropna().value_counts()
    ratings = p.data.customers.set_index("customer_id")["credit_rating"]
    return [{"customer_id": c, "credit_rating": ratings.get(c), "n_prs": int(n)} for c, n in counts.items()]


@app.get("/lots/{run_id}/{lot_id}/requisitions")
def lot_requisitions(run_id: str, lot_id: str):
    _check_run(run_id)
    p = planner()
    lots = p.run_result(run_id).lots.set_index("lot_id")
    if lot_id not in lots.index:
        raise HTTPException(404, f"unknown lot {lot_id}")
    ids = lots.loc[lot_id, "pr_ids"].split(",")
    return _records(p.prs.loc[ids, ["pr_id", "size_id", "channel_id", "requested_qty", "rdd_original",
                                    "customer_id", "nsv"]].reset_index(drop=True))


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
    if body.decision not in DECISIONS:
        raise HTTPException(400, f"decision must be one of {DECISIONS}")
    try:
        store().set_lot(planner(), run_id, lot_id, body.decision, body.factory, body.note)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    return get_overrides(run_id)


@app.delete("/overrides/{run_id}/lots/{lot_id}")
def revert_lot(run_id: str, lot_id: str):
    _check_run(run_id)
    store().set_lot(planner(), run_id, lot_id, "Buy", None, "")
    return get_overrides(run_id)


@app.post("/overrides/{run_id}/holds")
def add_hold(run_id: str, body: Hold):
    _check_run(run_id)
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
@lru_cache(maxsize=128)
def _pull_forward(run_id: str):
    p = planner()
    return {"windows": _records(pull_forward.window_utilization(p, run_id)),
            "recommendations": _records(pull_forward.recommendations(p, run_id))}


@app.get("/pull-forward/{run_id}")
def pull_forward_view(run_id: str):
    _check_run(run_id)
    return _pull_forward(run_id)


@app.get("/capacity/{run_id}")
def capacity(run_id: str, weeks_before: int = 4, weeks_after: int = 36):
    _check_run(run_id)
    p = planner()
    t = p.snapshots[run_id].table()
    t["week"] = pd.to_datetime(t["week"])
    start = pd.Timestamp(p.runs.set_index("run_id").loc[run_id, "mrp_freeze_datetime_utc"]).normalize()
    t = t[(t["week"] >= start - pd.Timedelta(weeks=weeks_before)) & (t["week"] <= start + pd.Timedelta(weeks=weeks_after))]
    return _records(t)


# ------------------------------------------------------------------ export
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
