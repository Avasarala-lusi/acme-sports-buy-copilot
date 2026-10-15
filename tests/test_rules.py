"""Unit tests for each rule, using small hand-made inputs."""
from datetime import date

import pandas as pd
import pytest

from engine.calendar import BuyingCalendar, production_weeks, weeks_between
from engine.capacity import CapacityLedger
from engine.pull_forward import window_stats
from engine.rules import exclusion, timing
from engine.rules.assignment import ABOVE_THRESHOLD, OK as FITS, OVER_CAPACITY, OVER_LAST_CHANCE, REVIEW, choose_factory, choose_from_chain
from engine.rules.grouping import group_by_rdd
from engine.rules.quantities import OK, PIGGYBACK, SHORT, pick_to_fill, quantity_status

CAL = BuyingCalendar(week_of_month=3, po_weekday=2)  # third-week Wednesday


# ---- buying windows (client: monthly, third week)
def test_window_is_the_third_week_po_weekday():
    assert CAL.window_in_month(2025, 8) == date(2025, 8, 20)
    assert CAL.window_in_month(2025, 12) == date(2025, 12, 17)
    assert all(15 <= CAL.window_in_month(2026, m).day <= 21 for m in range(1, 13))


def test_window_navigation():
    assert CAL.on_or_after(date(2025, 8, 6)) == date(2025, 8, 20)
    assert CAL.on_or_after(date(2025, 8, 20)) == date(2025, 8, 20)
    assert CAL.on_or_after(date(2025, 8, 27)) == date(2025, 9, 17)
    assert CAL.after(date(2025, 12, 17)) == date(2026, 1, 21)
    assert CAL.on_or_before(date(2026, 3, 10)) == date(2026, 2, 18)
    assert CAL.is_window(date(2025, 9, 17)) and not CAL.is_window(date(2025, 9, 10))


# ---- Rule 1
def test_release_date():
    assert timing.release_date("2026-03-01", 45, 60) == pd.Timestamp("2025-11-16")


def test_buy_now_when_release_before_next_window():
    nxt = date(2025, 9, 17)  # window Aug 20, next Sep 17
    assert timing.is_due(date(2025, 9, 16), nxt)
    assert not timing.is_due(date(2025, 9, 17), nxt)


# ---- Rule 5 / Rule 6
def test_wholesale_without_order_is_excluded():
    assert exclusion.forecast_excluded("01", has_order=False, early_buy=False)


def test_early_buy_and_orders_are_not_excluded():
    assert not exclusion.forecast_excluded("01", has_order=False, early_buy=True)
    assert not exclusion.forecast_excluded("01", has_order=True, early_buy=False)
    assert not exclusion.forecast_excluded("02", has_order=False, early_buy=False)


# ---- Rule 2
def test_grouping_anchor_vs_chain():
    rdds = ["2026-01-01", "2026-01-10", "2026-01-20", "2026-02-20"]
    assert group_by_rdd(rdds, 15, "anchor") == [[0, 1], [2], [3]]
    assert group_by_rdd(rdds, 15, "chain") == [[0, 1, 2], [3]]


def test_grouping_boundary_is_inclusive():
    assert group_by_rdd(["2026-01-01", "2026-01-16"], 15, "anchor") == [[0, 1]]
    assert group_by_rdd(["2026-01-01", "2026-01-17"], 15, "anchor") == [[0], [1]]


# ---- Rule 3 / Rule 4
@pytest.mark.parametrize("qty,expected", [(300, OK), (450, OK), (285, PIGGYBACK), (299, PIGGYBACK),
                                          (284, SHORT), (250, SHORT)])
def test_quantity_status_moq(qty, expected):
    assert quantity_status(qty, 300, 5) == expected


def test_hand_example_hold_below_moq():
    # 400-unit lot, 150 units held -> 250 left, below MOQ 300 and outside the 5% tolerance
    assert quantity_status(400 - 150, 300, 5) == SHORT


def test_pick_to_fill_takes_whole_requisitions_in_order():
    assert pick_to_fill(20, [("a", 10), ("b", 15), ("c", 50)]) == ["a", "b"]
    assert pick_to_fill(100, [("a", 10), ("b", 15)]) == []


# ---- capacity routing: loads include the incoming lot
def test_stays_on_primary_below_threshold():
    a = choose_factory("P", "B", {"P", "B"}, 50, 10, 85)
    assert a.factory == "P" and not a.routed_to_backup and a.status == FITS and not a.warnings


def test_routes_to_backup_at_threshold():
    a = choose_factory("P", "B", {"P", "B"}, 85, 10, 85)
    assert a.factory == "B" and a.routed_to_backup and a.status == FITS


def test_review_case_84_percent_plus_new_lot():
    # capacity 1,000, 840 already allocated, new lot of 500: 84% before, 134% with the lot
    ledger = CapacityLedger({"P": 1000}, spread=False)
    start = date(2026, 1, 5)
    ledger.add("P", start, 7, 840)
    weeks = ledger.weeks_for(start, 7)
    assert ledger.utilization("P", weeks) == pytest.approx(84.0)
    load = ledger.utilization_with("P", start, 7, 500)
    assert load == pytest.approx(134.0)
    a = choose_factory("P", "B", {"P"}, load, None, 85)
    assert a.status == REVIEW and "planner review" in a.warnings[0].lower()


def test_both_above_threshold_but_within_limit_is_bought_with_warning():
    a = choose_factory("P", "B", {"P", "B"}, 97, 92, 85)
    assert a.factory == "B" and a.status == ABOVE_THRESHOLD and a.warnings


def test_no_room_last_chance_is_bought_over_capacity_with_warning():
    a = choose_factory("P", "B", {"P", "B"}, 130, 120, 85, last_chance=True)
    assert a.factory == "B" and a.status == OVER_LAST_CHANCE and "Over capacity" in a.warnings[0]


def test_no_room_policy_buy_with_warning():
    a = choose_factory("P", "B", {"P", "B"}, 130, 120, 85, no_capacity_policy="buy_with_warning")
    assert a.status == OVER_CAPACITY


def test_uncertified_backup_is_never_used():
    a = choose_factory("P", "B", {"P"}, 99, None, 85)
    assert a.factory == "P" and a.warnings


def test_uncertified_primary_raises():
    with pytest.raises(ValueError):
        choose_factory("P", "B", {"B"}, 0, 0, 85)


# ---- capacity ledger
def test_ledger_spreads_units_over_manufacturing_weeks():
    ledger = CapacityLedger({"F": 1000})
    start = date(2026, 1, 5)  # Monday
    ledger.add("F", start, 14, 600)  # two weeks
    weeks = production_weeks(start, 14)
    assert len(weeks) == 2
    assert ledger.utilization("F", weeks) == pytest.approx(30.0)
    assert ledger.utilization_with("F", start, 14, 400) == pytest.approx(50.0)
    ledger.remove("F", start, 14, 600)
    assert ledger.utilization("F", weeks) == pytest.approx(0.0)


# ---- window load (pull-forward)
def test_window_average_uses_the_same_weeks_above_and_below():
    ledger = CapacityLedger({"F": 1000}, spread=False)
    weeks = weeks_between(date(2026, 1, 21), date(2026, 2, 18))
    assert len(weeks) == 4
    for w in weeks:
        ledger.add("F", w, 7, 900)
    s = window_stats(ledger, "F", weeks)
    assert s["avg_pct"] == pytest.approx(90.0) and s["peak_pct"] == pytest.approx(90.0)


def test_window_peak_shows_a_week_the_average_hides():
    ledger = CapacityLedger({"F": 1000}, spread=False)
    weeks = weeks_between(date(2026, 1, 21), date(2026, 2, 18))
    for w, u in zip(weeks, [1200, 600, 600, 600]):
        ledger.add("F", w, 7, u)
    s = window_stats(ledger, "F", weeks)
    assert s["avg_pct"] == pytest.approx(75.0) and s["peak_pct"] == pytest.approx(120.0)


def test_chain_walks_to_the_next_backup_with_room():
    a = choose_from_chain("TR05", ["BD02", "IN06", "CN04"], {"TR05", "BD02", "IN06", "CN04"},
                          {"TR05": 95, "BD02": 90, "IN06": 40, "CN04": 10}, 85)
    assert a.factory == "IN06" and a.routed_to_backup and "backup no. 2" in a.reasons[0]


def test_chain_skips_uncertified_backups():
    a = choose_from_chain("VN01", ["ID03", "CN04"], {"VN01", "CN04"}, {"VN01": 90, "CN04": 50}, 85)
    assert a.factory == "CN04"


def test_chain_with_no_room_goes_to_review():
    a = choose_from_chain("VN01", ["ID03", "CN04"], {"VN01", "ID03", "CN04"},
                          {"VN01": 130, "ID03": 120, "CN04": 110}, 85)
    assert a.status == REVIEW
