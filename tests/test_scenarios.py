"""What-if scenarios checked against hand calculations on real lots."""
import pandas as pd
import pytest

from engine import pull_forward
from sim import scenarios
from tests.conftest import needs_data

pytestmark = needs_data
RUN = "MRP-WK019"
HELD = "KEY-AMAZON"  # largest account in this run (data v5 names every DTC account)


def test_hold_customer_removes_exactly_their_units(planner):
    lots = planner.results[RUN].lots
    ids = lots["pr_ids"].str.split(",").explode()
    customer = planner.prs.loc[ids, "customer_id"].dropna().loc[lambda s: s.str.startswith("CUST")].iloc[0]
    held = planner.prs.loc[ids][planner.prs.loc[ids, "customer_id"] == customer]

    r = scenarios.hold_customer(planner, RUN, customer)

    assert r["nsv_at_risk_usd"] == pytest.approx(held["nsv"].sum())
    assert r["lots"]["qty_removed"].sum() == pytest.approx(held["requested_qty"].sum())
    assert (r["lots"]["qty_after"] == r["lots"]["qty_before"] - r["lots"]["qty_removed"]).all()
    assert (r["lots"]["decision_type"] == "manual").all()


def test_hold_flags_lots_that_fall_below_moq(planner):
    r = scenarios.hold_customer(planner, RUN, HELD)
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


@pytest.mark.parametrize("run", [RUN, "MRP-WK021", "MRP-WK040"])
def test_pull_forward_moves_are_tested_together(planner, run):
    """Replaying every accepted move on one ledger keeps every target below the threshold."""
    threshold = planner.cfg["capacity"]["backup_threshold_pct"]
    rec = pull_forward.recommendations(planner, run)
    accepted = rec[rec["actionable"]] if len(rec) else rec
    assert (accepted["target_peak_after_pct"] <= threshold).all()  # below the threshold, stored to 1 dp
    assert accepted["moq_ok_for_market"].all() and accepted["mpq_target_ok"].all() and accepted["mpq_source_ok"].all()
    assert (accepted["source_peak_after_pct"] <= accepted["overloaded_util_pct"] + 1e-9).all()


def test_window_utilization_counts_the_same_weeks(planner):
    u = pull_forward.window_utilization(planner, RUN)
    cap = planner.factories["weekly_capacity_units"]
    expected = u["units"] / (u["factory_id"].map(cap) * u["weeks"]) * 100
    assert (u["avg_utilization_pct"] - expected).abs().max() < 1e-9
    assert (u["peak_utilization_pct"] >= u["avg_utilization_pct"] - 1e-9).all()


# ---- customer hold: fixes never use the held customer, never reuse a requisition
@pytest.mark.parametrize("customer", [HELD, "CUST-0001"])
def test_hold_fix_never_pulls_the_held_customer_or_reuses_demand(planner, customer):
    for run in planner.buying_runs():
        r = scenarios.hold_customer(planner, run, customer)
        if not r["lots_affected"]:
            continue
        pulled = r["lots"]["pulled_pr_ids"].str.split(",").explode()
        pulled = pulled[pulled != ""]
        assert not (planner.prs.loc[pulled, "customer_id"] == customer).any(), run
        assert not pulled.duplicated().any(), run


def test_hold_rechecks_minimums_after_the_fix(planner):
    r = scenarios.hold_customer(planner, RUN, HELD)
    lots = r["lots"]
    for col in ["moq_ok_after_fix", "mpq_ok_after_fix", "factory_total_after", "factory_load_after_pct"]:
        assert col in lots
    assert (lots["moq_ok_after_fix"] == ((lots["qty_after_fix"] == 0) | (lots["qty_after_fix"] >= 300))).all()


# ---- factory switch: load after removing the lot from its factory and adding it to the target
def test_swap_capacity_is_measured_after_the_move(planner):
    lots = planner.results[RUN].lots
    lot = lots[lots["auto_decision"] == "Buy"].iloc[0]
    target = next(f for f in sorted(planner.certified[lot["article_id"]]) if f != lot["assigned_factory"])
    r = scenarios.swap_factory(planner, RUN, lot["lot_id"], target)

    ledger = planner.snapshots[RUN].copy()
    ledger.remove(lot["assigned_factory"], lot["production_start"], int(lot["mfg_days"]), lot["consolidated_qty"])
    m, t = planner.lot_lead_times(lot["pr_ids"].split(","), target)
    start = planner.results[RUN].buy_date
    weeks = ledger.weeks_for(start, m)
    expected = ledger.utilization_with(target,start,m,lot["consolidated_qty"])

    assert r["target_utilization_pct"] == pytest.approx(expected, abs=0.05)
    assert r["target_utilization_pct"] > r["target_load_before_pct"]
    assert r["source_load_after_pct"] < r["source_load_before_pct"]
    assert r["capacity_warning"] == (r["target_utilization_pct"] >= planner.cfg["capacity"]["backup_threshold_pct"])
