"""Unit tests for each rule, using small hand-made inputs."""
from datetime import date

import pandas as pd
import pytest

from engine.calendar import natural_window, next_window_cutoff, production_weeks, window_cutoff
from engine.capacity import CapacityLedger
from engine.rules import exclusion, timing
from engine.rules.assignment import choose_factory
from engine.rules.grouping import group_by_rdd
from engine.rules.quantities import OK, PIGGYBACK, SHORT, pick_to_fill, quantity_status

CUTOFF = 21


# ---- buying windows (client: monthly, third week)
def test_window_cutoff_same_month_when_before_cutoff():
    assert window_cutoff(date(2025, 8, 3), CUTOFF) == date(2025, 8, 21)


def test_window_cutoff_rolls_to_next_month_after_cutoff():
    assert window_cutoff(date(2025, 8, 24), CUTOFF) == date(2025, 9, 21)
    assert next_window_cutoff(date(2025, 12, 24), CUTOFF) == date(2026, 2, 21)


def test_natural_window():
    assert natural_window(date(2026, 3, 25), CUTOFF) == date(2026, 3, 21)
    assert natural_window(date(2026, 3, 10), CUTOFF) == date(2026, 2, 21)


# ---- Rule 1
def test_release_date():
    assert timing.release_date("2026-03-01", 45, 60) == pd.Timestamp("2025-11-16")


def test_buy_now_when_release_before_next_window():
    run = date(2025, 8, 3)  # current window Aug 21, next Sep 21
    assert timing.is_due(date(2025, 9, 20), run, CUTOFF)
    assert not timing.is_due(date(2025, 9, 21), run, CUTOFF)


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


# ---- capacity routing
def test_stays_on_primary_below_threshold():
    a = choose_factory("P", "B", {"P", "B"}, 50, 10, 85, "least_loaded_with_warning")
    assert a.factory == "P" and not a.routed_to_backup and not a.warnings


def test_routes_to_backup_at_threshold():
    a = choose_factory("P", "B", {"P", "B"}, 85, 10, 85, "least_loaded_with_warning")
    assert a.factory == "B" and a.routed_to_backup


def test_both_full_goes_to_least_loaded_with_warning():
    a = choose_factory("P", "B", {"P", "B"}, 120, 95, 85, "least_loaded_with_warning")
    assert a.factory == "B" and a.warnings


def test_uncertified_backup_is_never_used():
    a = choose_factory("P", "B", {"P"}, 99, None, 85, "least_loaded_with_warning")
    assert a.factory == "P" and a.warnings


def test_uncertified_primary_raises():
    with pytest.raises(ValueError):
        choose_factory("P", "B", {"B"}, 0, 0, 85, "least_loaded_with_warning")


# ---- capacity ledger
def test_ledger_spreads_units_over_manufacturing_weeks():
    ledger = CapacityLedger({"F": 1000})
    start = date(2026, 1, 5)  # Monday
    ledger.add("F", start, 14, 600)  # two weeks
    weeks = production_weeks(start, 14)
    assert len(weeks) == 2
    assert ledger.utilization("F", weeks) == pytest.approx(30.0)
    ledger.remove("F", start, 14, 600)
    assert ledger.utilization("F", weeks) == pytest.approx(0.0)
