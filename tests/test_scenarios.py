"""What-if scenarios checked against hand calculations on real lots."""
import pandas as pd
import pytest

from engine import pull_forward
from sim import scenarios
from tests.conftest import needs_data

pytestmark = needs_data
RUN = "MRP-WK020"


def test_hold_customer_removes_exactly_their_units(planner):
    lots = planner.results[RUN].lots
    ids = lots["pr_ids"].str.split(",").explode()
    customer = planner.prs.loc[ids, "customer_id"].dropna().loc[lambda s: s != "DTC"].iloc[0]
    held = planner.prs.loc[ids][planner.prs.loc[ids, "customer_id"] == customer]

    r = scenarios.hold_customer(planner, RUN, customer)

    assert r["nsv_at_risk_usd"] == pytest.approx(held["nsv"].sum())
    assert r["lots"]["qty_removed"].sum() == pytest.approx(held["requested_qty"].sum())
    assert (r["lots"]["qty_after"] == r["lots"]["qty_before"] - r["lots"]["qty_removed"]).all()
    assert (r["lots"]["decision_type"] == "manual").all()


def test_hold_flags_lots_that_fall_below_moq(planner):
    r = scenarios.hold_customer(planner, RUN, "DTC")
    after = r["lots"]
    below = after[(after["qty_after"] > 0) & (after["qty_after"] < 300)]
    assert set(below["lot_id"]) == set(r["moq_alerts"]["lot_id"])


def test_delay_shifts_arrival_by_n_days(planner):
    factory = planner.results[RUN].lots["assigned_factory"].iloc[0]
    r = scenarios.delay_factory(planner, RUN, factory, 10)
    shift = (r["lots"]["arrival_after"] - r["lots"]["arrival_before"]).dt.days
    assert (shift == 10).all()
    assert (r["lots"]["late_after"] == (r["lots"]["late_units"] > 0)).all()


def test_swap_rejects_uncertified_factory(planner):
    lot = planner.results[RUN].lots.iloc[0]
    bad = next(f for f in planner.factories.index if f not in planner.certified[lot["article_id"]])
    assert scenarios.swap_factory(planner, RUN, lot["lot_id"], bad)["valid"] is False


def test_swap_cost_delta_uses_cost_multipliers(planner):
    lot = planner.results[RUN].lots.iloc[0]
    target = next(f for f in planner.certified[lot["article_id"]] if f != lot["assigned_factory"])
    r = scenarios.swap_factory(planner, RUN, lot["lot_id"], target)
    expected = lot["consolidated_qty"] * lot["unit_cost_usd"] * (
        planner.factories.loc[target, "cost_multiplier"] - lot["cost_multiplier"])
    assert r["valid"] and r["cost_delta_usd"] == pytest.approx(expected)
    assert r["decision_type"] == "manual"


def test_pull_forward_only_flags_windows_at_or_above_threshold(planner):
    rec = pull_forward.recommendations(planner, RUN)
    assert (rec["overloaded_util_pct"] >= planner.cfg["capacity"]["backup_threshold_pct"] - 0.05).all()
