"""Manual Go/No-Go decisions: saved separately, applied on top of the automatic plan, reversible."""
import pytest

from engine.overrides import OverrideStore, effective_fact_table, effective_lots
from sim import scenarios
from tests.conftest import needs_data

pytestmark = needs_data
RUN = "MRP-WK020"


@pytest.fixture
def store(tmp_path):
    return OverrideStore(tmp_path / "overrides.json")


def test_no_overrides_means_automatic_plan(planner, store):
    eff = effective_lots(planner, RUN, store)
    assert (eff["decision"] == "Buy").all()
    assert (eff["decision_type"] == "auto").all()
    assert len(effective_fact_table(planner, RUN, store)) == len(planner.results[RUN].lots)


def test_no_go_removes_lot_from_buy_plan(planner, store):
    lot = planner.results[RUN].lots["lot_id"].iloc[0]
    store.set_lot(planner, RUN, lot, "No-Go", note="customer cancelled")
    eff = effective_lots(planner, RUN, store).set_index("lot_id")
    assert eff.loc[lot, "decision"] == "No-Go" and eff.loc[lot, "decision_type"] == "manual"
    assert lot not in set(effective_fact_table(planner, RUN, store)["suggestion_id"].str[4:])


def test_factory_switch_matches_scenario_cost(planner, store):
    lots = planner.results[RUN].lots
    lot = lots.iloc[0]
    target = next(f for f in sorted(planner.certified[lot["article_id"]]) if f != lot["assigned_factory"])
    store.set_lot(planner, RUN, lot["lot_id"], "Buy", target)
    eff = effective_lots(planner, RUN, store).set_index("lot_id").loc[lot["lot_id"]]
    expected = scenarios.swap_factory(planner, RUN, lot["lot_id"], target)
    assert eff["assigned_factory"] == target
    assert eff["total_cost_usd"] == pytest.approx(expected["cost_after_usd"])
    assert eff["expected_arrival"] == expected["arrival_after"]


def test_uncertified_switch_is_rejected(planner, store):
    lot = planner.results[RUN].lots.iloc[0]
    bad = next(f for f in planner.factories.index if f not in planner.certified[lot["article_id"]])
    with pytest.raises(ValueError):
        store.set_lot(planner, RUN, lot["lot_id"], "Buy", bad)


def test_customer_hold_matches_scenario(planner, store):
    sc = scenarios.hold_customer(planner, RUN, "DTC")
    store.hold_customer(RUN, "DTC")
    eff = effective_lots(planner, RUN, store).set_index("lot_id")
    for row in sc["lots"].itertuples():
        assert eff.loc[row.lot_id, "consolidated_qty"] == row.qty_after
        if row.qty_after == 0:
            assert eff.loc[row.lot_id, "decision"] == "No-Go"


def test_overrides_persist_and_revert(planner, store, tmp_path):
    lot = planner.results[RUN].lots["lot_id"].iloc[0]
    store.set_lot(planner, RUN, lot, "Delay")
    store.hold_customer(RUN, "DTC")
    reloaded = OverrideStore(tmp_path / "overrides.json")
    assert reloaded.count(RUN) == 2
    reloaded.reset(RUN)
    assert OverrideStore(tmp_path / "overrides.json").count(RUN) == 0


def test_engine_plan_is_never_modified(planner, store):
    before = planner.results[RUN].lots.copy()
    store.hold_customer(RUN, "DTC")
    effective_lots(planner, RUN, store)
    assert planner.results[RUN].lots.equals(before)
