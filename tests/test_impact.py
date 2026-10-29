"""Late-delivery impact: every firm unit is counted once, values scale with the price, baseline capacity is real."""
import pytest

from engine.impact import impact_report, requisition_status
from engine.planner import FUTURE_FORECAST, OPEN
from tests.conftest import needs_data

pytestmark = needs_data


def test_every_firm_unit_has_one_status(planner):
    df = requisition_status(planner)
    out = planner.pr_outcomes()
    firm = out[~out["outcome"].isin([FUTURE_FORECAST, OPEN])]
    assert len(df) == len(firm) and df["pr_id"].is_unique
    assert set(df["plan_status"]) <= {"on time", "late", "not bought (planner)"}
    r = impact_report(planner)
    for side in ["plan", "baseline"]:
        assert sum(v["units"] for v in r[side].values()) == pytest.approx(r["firm_units"])


def test_values_scale_with_the_price(planner):
    a, b = impact_report(planner, 21), impact_report(planner, 42)
    assert b["extra_usd_at_price"] == pytest.approx(2 * a["extra_usd_at_price"])
    assert a["extra_usd_range"][0] < a["extra_usd_at_price"] < a["extra_usd_range"][1]


def test_breakdowns_add_up(planner):
    r = impact_report(planner)
    for dim in ["by_market", "by_category", "by_channel"]:
        assert sum(x["units"] for x in r[dim]) == pytest.approx(r["firm_units"])
        assert sum(x["extra_late_or_unbought_units"] for x in r[dim]) == pytest.approx(r["extra_units_not_on_time"])


def test_baseline_capacity_overload_is_measured(planner):
    r = impact_report(planner)
    assert r["baseline_units_above_capacity"] > 0 and r["baseline_peak_utilization_pct"] > 100
