"""On-time probability, network optimiser, disruption drill, planner benchmark and data health."""
import copy

import numpy as np
import pandas as pd
import pytest

from tests.conftest import needs_data

pytestmark = needs_data


@pytest.fixture(scope="module")
def network(planner):
    from engine.optimizer import Network
    return Network(planner)


def test_on_time_probability_rises_with_buffer(planner):
    from engine.risk import DelayModel
    m = DelayModel(planner)
    p = m.p_on_time("ACME-VN01", np.array([-30.0, 0.0, 3.0, 30.0]))
    assert p[0] == 0.0 and p[-1] == 1.0 and np.all(np.diff(p) >= 0)


def test_risk_report_is_consistent(planner):
    from engine.risk import risk_report
    r = risk_report(planner)
    assert r["units"] == pytest.approx(planner.bought_lots()["consolidated_qty"].sum())
    assert 0 < r["expected_on_time_pct"] < 100
    assert sum(b["units"] for b in r["bands"]) == pytest.approx(r["units"])


def test_optimiser_respects_capacity_certification_and_mpq(planner, network):
    from engine.optimizer import evaluate
    from engine.rules.quantities import mpq_for
    s = network.solve(0.5, time_limit=20)
    choice, opts, u = s["choice"], network.opts, network.u
    o = opts.loc[choice[choice >= 0].to_numpy()]
    assert all(f in planner.certified[a] for f, a in zip(o["factory"], u.loc[o["lot"], "article_id"]))
    e = evaluate(planner, u, opts, choice)
    assert e["weeks_over_100"] == 0 and e["orders_below_mpq"] == 0
    rules = evaluate(planner, u, opts, network.rule)
    assert e["units_bought"] >= rules["units_bought"]


def test_cheapest_plan_costs_less_than_safest(planner, network):
    from engine.optimizer import evaluate
    cheap = evaluate(planner, network.u, network.opts, network.solve(0.0, time_limit=20)["choice"])
    safe = evaluate(planner, network.u, network.opts, network.solve(1.0, time_limit=20)["choice"])
    assert cheap["cost_per_unit_usd"] < safe["cost_per_unit_usd"]
    assert safe["expected_on_time_units"] > cheap["expected_on_time_units"]


def test_drill_keeps_closed_weeks_empty(planner, network):
    from engine.drill import run_drill
    r = run_drill(planner, "ACME-VN01", "2026-09-01", "2026-10-31", 0.5, network)
    assert r["affected_lots"] > 0
    assert r["plans"]["rules_disrupted"]["units_in_closed_weeks"] == 0
    assert r["plans"]["optimiser_disrupted"]["units_in_closed_weeks"] == 0
    assert r["plans"]["rules_disrupted"]["weeks_over_100"] == 0


def test_benchmark_chooses_on_tuning_seasons_only(planner):
    from engine.benchmark import cached_network_results
    r = cached_network_results(planner)
    assert set(r["tuning_seasons"]).isdisjoint(r["test_seasons"])
    assert r["selected_weight"] in r["weights"]
    rules = next(a for a in r["approaches"] if a["key"] == "rules")
    assert rules["results"]["all"]["units_bought"] == pytest.approx(planner.bought_lots()["consolidated_qty"].sum())


def test_data_health_flags_injected_anomalies(planner):
    from engine.data_health import health_report
    p = copy.copy(planner)
    p.data = copy.copy(planner.data)
    p.data.tables = dict(planner.data.tables)
    prs = planner.data.prs.copy()
    prs.loc[0, "requested_qty"] = prs.loc[0, "requested_qty"] * 100
    prs = pd.concat([prs, prs.iloc[[1]]], ignore_index=True)
    p.data.tables["prs"] = prs
    r = health_report(p, prs.loc[0, "run_id"])
    flagged = {(f["pr_id"], f["check"]) for f in r["run"]["flags"]}
    assert (prs.loc[0, "pr_id"], "qty_outlier") in flagged
    dup = health_report(p, prs.loc[1, "run_id"])["run"]["flags"]
    assert any(f["pr_id"] == prs.loc[1, "pr_id"] and f["check"] == "duplicate" for f in dup)
