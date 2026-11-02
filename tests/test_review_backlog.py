"""Outstanding exceptions remain actionable without inventing purchases or capacity."""
from collections import Counter
from copy import deepcopy

import pytest

from engine.accounting import accounting_report
from engine.overrides import OverrideStore, effective_lots
from engine.planner import Planner
from tests.test_client_clarifications import small_planner


def review_ids(result):
    lots = result.lots
    if lots.empty:
        return []
    decision = "decision" if "decision" in lots else "auto_decision"
    return [p for ids in lots.loc[lots[decision] == "Review", "pr_ids"] for p in ids.split(",") if p]


def test_overdue_review_reappears_in_drafts_and_later_buying_windows():
    p = small_planner(capacity=100)
    p.plan_through("R2")
    first_id = p.results["R2"].lots.iloc[0].lot_id
    for run in ("R3", "R4", "R5"):
        result = p.run_result(run)
        assert review_ids(result) == ["P0"]
        assert result.lots.iloc[0].lot_id != first_id
        assert result.outcomes.set_index("pr_id").loc["P0", "lot_id"] == result.lots.iloc[0].lot_id
        assert p.ledger.table().empty
    assert p.bought_lots().empty
    assert accounting_report(p)["passed"]


def test_visibility_check_rejects_a_status_without_a_current_row():
    p = small_planner(capacity=100)
    p.plan_all()
    p.results["R5"].lots = p.results["R5"].lots.iloc[0:0]
    assert not accounting_report(p)["checks"]["review_prs_visible"]


def test_quantity_shortfalls_are_actionable_without_waiving_minimums(tmp_path):
    for qty in (100, 600):
        p = small_planner((qty,))
        p.plan_all()
        result = p.results["R4"]
        assert review_ids(result) == ["P0"]
        store = OverrideStore(tmp_path / f"{qty}.json")
        store.set_lot(p, "R4", result.lots.iloc[0].lot_id, "Buy", note="Try approval")
        effective = store.replay(p)
        effective.plan_all()
        assert effective.bought_lots().empty
        assert review_ids(effective.results["R5"]) == ["P0"]
        assert effective.ledger.table().empty


def test_review_can_be_approved_later_once_capacity_is_available(tmp_path):
    seed = small_planner((1200, 1200), capacity=1200)
    data = deepcopy(seed.data)
    data.tables["prs"].loc[1, "market_destination"] = "MX"
    p = Planner(data, deepcopy(seed.cfg))
    p.plan_all()
    assert len(p.bought_lots()) == 1
    row = p.results["R4"].lots.query("auto_decision == 'Review'").iloc[0]
    pending = row.pr_ids
    assert pending not in p.bought_lots().pr_ids.tolist()
    store = OverrideStore(tmp_path / "approve.json")
    store.set_lot(p, "R4", row.lot_id, "Buy", note="Approve late arrival")
    effective = store.replay(p)
    effective.plan_all()
    bought = effective.bought_lots()
    ids = [pid for group in bought.pr_ids for pid in group.split(",")]
    assert Counter(ids) == Counter(["P0", "P1"])
    assert pending not in review_ids(effective.results["R5"])
    assert effective.ledger.table().units.sum() == pytest.approx(2400)
    assert effective.ledger.table().utilization_pct.max() <= 100
    assert accounting_report(effective)["passed"]


def test_cancelled_backlog_stays_out_of_subsequent_review(tmp_path):
    p = small_planner(capacity=100)
    p.plan_all()
    store = OverrideStore(tmp_path / "cancel.json")
    store.set_lot(p, "R4", p.results["R4"].lots.iloc[0].lot_id, "No-Go")
    effective = store.replay(p)
    effective.plan_all()
    assert "P0" not in review_ids(effective.results["R5"])
    assert effective.pr_outcomes().set_index("pr_id").loc["P0", "outcome"] == "CANCELLED"
    assert effective.ledger.table().empty


def test_reverting_the_last_lot_decision_restores_the_exact_automatic_reference(tmp_path):
    p = small_planner((100,)); p.plan_all()
    store = OverrideStore(tmp_path / "revert.json")
    lot = p.results["R2"].lots.iloc[0]
    store.set_lot(p, "R2", lot.lot_id, "No-Go")
    store.revert_lot("R2", lot.lot_id)
    assert store.replay(p) is p
    assert store.replay(p).results["R2"].outcomes.equals(p.results["R2"].outcomes)


def test_last_chance_forecast_conflict_is_visible_but_not_automatically_confirmed(tmp_path):
    seed = small_planner(last_chance=True)
    data = deepcopy(seed.data)
    data.tables["sales_orders"] = data.sales_orders.iloc[0:0]
    p = Planner(data, deepcopy(seed.cfg))
    p.plan_all()
    for result in p.results.values():
        assert review_ids(result) == ["P0"]
    store = OverrideStore(tmp_path / "conflict.json")
    store.set_lot(p, "R4", p.results["R4"].lots.iloc[0].lot_id, "Buy")
    effective = store.replay(p)
    effective.plan_all()
    assert effective.bought_lots().empty
    assert "unconfirmed wholesale" in effective.results["R4"].lots.iloc[0].warnings


def test_hold_remainder_and_unheld_customer_remain_actionable(tmp_path):
    p = small_planner((600, 600))
    p.plan_all()
    store = OverrideStore(tmp_path / "hold.json")
    store.hold_customer("R2", "C0")
    effective = store.replay(p)
    effective.plan_all()
    ids = review_ids(effective.results["R4"])
    assert Counter(ids) == Counter(["P0", "P1"])
    assert effective.bought_lots().empty
    row = effective.results["R4"].lots.query("auto_decision == 'Review'").iloc[0]
    store.set_lot(effective, "R4", row.lot_id, "Buy", note="Approve after hold")
    approved = store.replay(p)
    approved.plan_all()
    assert approved.bought_lots().consolidated_qty.sum() == 1200
    assert review_ids(approved.results["R5"]) == []
    assert accounting_report(approved)["passed"]
