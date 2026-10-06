"""FastAPI service over the planning engine, for a custom web front end.

Run with:  uvicorn api.main:app --reload
"""
import io
import json
from functools import lru_cache

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from engine import pull_forward
from engine.accounting import accounting_report
from engine.metrics import plan_kpis
from engine.output import fact_buy_plan_suggestions, get_planner
from sim import scenarios

app = FastAPI(title="Acme Sports Buy Planner API", version="0.1.0")


@lru_cache
def planner():
    return get_planner()


def _records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", date_format="iso"))


def _check_run(run_id: str):
    if run_id not in planner().run_index:
        raise HTTPException(404, f"unknown run {run_id}")


@app.get("/runs")
def runs():
    cols = ["run_id", "week_number", "mrp_freeze_datetime_utc", "go_nogo_date", "po_execution_date",
            "season", "range_version", "quarter"]
    return _records(planner().runs[cols])


@app.get("/plan/{run_id}")
def plan(run_id: str):
    _check_run(run_id)
    r = planner().run_result(run_id)
    return {"run_id": run_id, "kpis": plan_kpis(planner(), [run_id]), "lots": _records(r.lots),
            "decisions": _records(r.outcomes), "waiting_pr_ids": r.open_prs}


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
        return {k: _records(v) if isinstance(v, pd.DataFrame) else v for k, v in r.items()}
    if s.type == "delay":
        r = scenarios.delay_factory(p, s.run_id, s.factory, s.days)
        return {k: _records(v) if isinstance(v, pd.DataFrame) else v for k, v in r.items()}
    if s.type == "swap":
        r = scenarios.swap_factory(p, s.run_id, s.lot_id, s.target_factory)
        return json.loads(json.dumps(r, default=str))
    raise HTTPException(400, f"unknown scenario type {s.type}")


@app.get("/pull-forward/{run_id}")
def pull_forward_view(run_id: str):
    _check_run(run_id)
    return {"windows": _records(pull_forward.window_utilization(planner(), run_id)),
            "recommendations": _records(pull_forward.recommendations(planner(), run_id))}


@app.get("/capacity/{run_id}")
def capacity(run_id: str):
    _check_run(run_id)
    return _records(planner().snapshots[run_id].table())


@app.get("/checks")
def checks():
    return json.loads(json.dumps(accounting_report(planner()), default=str))


@app.get("/export/{run_id}")
def export(run_id: str):
    _check_run(run_id)
    csv = fact_buy_plan_suggestions(planner(), [run_id]).to_csv(index=False)
    return StreamingResponse(io.StringIO(csv), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=buy_plan_{run_id}.csv"})
