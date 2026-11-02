"""Operational forecast chronology, honest model selection, and decision-state warnings."""
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from engine import forecast as fc
from engine.overrides import OverrideStore
from engine.planner import Planner
from tests.test_client_clarifications import small_planner


def demo(quantities=(1200,), capacity=10000):
    seed = small_planner(quantities, capacity=capacity)
    data = deepcopy(seed.data)
    data.tables["runs"] = data.runs.assign(season="FW26", range_version="V1")
    return Planner(data, deepcopy(seed.cfg))


def intake(date="2026-02-15", qty=1200):
    return pd.DataFrame([dict(factory="F", date=pd.Timestamp(date), p50=qty, p90=qty*1.4,
                              model="stage_seasonal")])


def test_forecast_production_never_precedes_intake_and_units_are_conserved():
    p = demo()
    p.plan_through("R2")
    before = p.ledger.table().copy()
    _, _, _, _, components = fc._load_ledgers(p, "R2", intake())
    assert components and all(c["production_start"] >= c["intake_date"] for c in components)
    assert sum(c["p50"] for c in components) == pytest.approx(1200)
    assert p.ledger.table().equals(before)


def test_draft_purchases_are_not_labelled_committed_forecast_load():
    p = demo()
    committed, known, _, _, _ = fc._load_ledgers(p, "R1", intake())
    assert committed.table().empty
    assert known.table().units.sum() == pytest.approx(1200)


def test_load_view_contains_exactly_four_future_purchase_windows():
    p = demo()
    _, windows = fc.forecast_load(p, "R2", intake())
    assert windows.window.nunique() == 4
    assert windows.window.iloc[0] == "WIN-2026-01-EOM"


def test_approval_warning_includes_a_bought_lot_once():
    p = demo(capacity=2400)
    p.plan_through("R2")
    lot = p.results["R2"].lots.iloc[0]
    warning = fc.decision_warning(p, "R2", lot.lot_id, intake=intake(qty=0))
    assert warning["committed_before_pct"] == 0
    assert warning["committed_after_pct"] == pytest.approx(30)  # 3/5 working days in the first week
    assert not warning["hard_capacity_blocked"]
    assert p.ledger.table().units.sum() == pytest.approx(1200)


def test_forecast_pressure_warns_without_blocking_a_feasible_purchase():
    seed = demo(capacity=800)
    data = deepcopy(seed.data)
    data.tables["prs"]["manufacturing_lead_time"] = 28
    data.tables["prs"]["rdd_original"] = pd.Timestamp("2026-02-11")
    data.tables["factories"][["mfg_lt_min_days", "mfg_lt_max_days"]] = 28
    p = Planner(data, deepcopy(seed.cfg)); p.plan_through("R2")
    row = p.results["R2"].lots.iloc[0]
    warning = fc.decision_warning(p, "R2", row.lot_id, intake=intake("2026-01-20", 2000))
    assert warning["forecast_warning"]
    assert not warning["hard_capacity_blocked"]
    assert p.bought_lots().consolidated_qty.sum() == 1200


def test_warning_uses_effective_saved_decisions_without_reserving_forecast(tmp_path):
    p = demo((1200, 1200), capacity=10000)
    data = deepcopy(p.data)
    data.tables["prs"].loc[1, "market_destination"] = "MX"
    p = Planner(data, deepcopy(p.cfg))
    p.plan_all()
    lot = p.results["R2"].lots.iloc[0]
    store = OverrideStore(tmp_path / "decisions.json")
    store.set_lot(p, "R2", lot.lot_id, "No-Go")
    effective = store.replay(p)
    effective.plan_through("R2")
    committed, _, _, _, _ = fc._load_ledgers(effective, "R2", intake(qty=0))
    assert committed.table().units.sum() == pytest.approx(1200)
    assert p.ledger.table().units.sum() == pytest.approx(2400)


def test_future_actuals_are_hidden_and_error_ranges_contain_the_point():
    p = demo()
    forecast = fc.forecast_intake(p, "R2")
    assert forecast.actual.isna().all()
    assert (forecast.p10 <= forecast.p50).all() and (forecast.p50 <= forecast.p90).all()
    assert forecast.fallback_reason.ne("").any()


def synthetic_series():
    return pd.DataFrame([dict(week=w, factory="F", units=100+10*np.sin(w/4),
        date=pd.Timestamp("2024-01-07")+pd.Timedelta(weeks=w-1), stage="0-1", season_ss=0.,
        range_version=1., weeks_into_stage=float(w-1)) for w in range(1, 101)])


@pytest.mark.parametrize("model", ["random_forest", "xgboost", "extra_trees", "gradient_boosting"])
def test_live_learners_receive_real_past_training_examples(monkeypatch, model):
    calls = []
    class Learner:
        def fit(self, x, y): calls.append(len(x))
        def predict(self, x): return np.ones(len(x))
    monkeypatch.setitem(fc.LEARNERS, model, Learner)
    result = fc.predict_model(synthetic_series(), 70, 17, model)
    assert calls and calls[0] >= 100
    assert set(result.used_model) == {model}


def test_calibration_uses_the_requested_model_and_only_known_targets(monkeypatch):
    calls = []
    def predict(series, origin, horizon, model, **kw):
        calls.append((origin, model))
        return pd.DataFrame([dict(week=origin+h, horizon=h, p50=50., actual=100.) for h in range(1,horizon+1)])
    monkeypatch.setattr(fc, "predict_model", predict)
    ratios = fc.error_ratios(synthetic_series(), 60, 17, "random_forest")
    assert all(o < 60 and m == "random_forest" for o, m in calls)
    assert all(np.allclose(x, 101/51) for x in ratios.values() if len(x))


def test_unknown_model_is_an_explicit_error():
    with pytest.raises(ValueError, match="unknown forecast model"):
        fc.predict_model(synthetic_series(), 60, 17, "invented")


def test_decision_endpoint_returns_a_real_boolean_and_preview_is_read_only(monkeypatch):
    from fastapi.testclient import TestClient
    import api.main as main
    p = demo(capacity=2400); p.plan_through("R2")
    lot = p.results["R2"].lots.iloc[0]
    monkeypatch.setattr(main, "planner", lambda: p)
    monkeypatch.setattr(main, "_intake_cached", lambda run, model: intake(qty=0))
    before = p.ledger.table().copy()
    response = TestClient(main.app).get(f"/forecast/R2/lots/{lot.lot_id}?factory=F")
    assert response.status_code == 200
    assert response.json()["hard_capacity_blocked"] is False
    assert p.ledger.table().equals(before)


def test_live_forecast_api_refreshes_load_but_not_demand_after_saved_no_go(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import api.main as main
    seed = demo()
    data = deepcopy(seed.data)
    data.tables["prs"]["manufacturing_lead_time"] = 28
    data.tables["prs"]["rdd_original"] = pd.Timestamp("2026-02-11")
    p = Planner(data, deepcopy(seed.cfg)); p.plan_all()
    active = [p]
    monkeypatch.setattr(main, "automatic_planner", lambda: p)
    monkeypatch.setattr(main, "planner", lambda: active[0])
    main._intake_cached.cache_clear()
    client = TestClient(main.app)
    before = client.get("/forecast/R2").json()
    lot = p.results["R2"].lots.iloc[0]
    store = OverrideStore(tmp_path / "saved.json")
    store.set_lot(p, "R2", lot.lot_id, "No-Go")
    active[0] = store.replay(p)
    after = client.get("/forecast/R2").json()
    assert before["intake"] == after["intake"]
    assert all(row["actual"] is None for row in after["intake"])
    assert sum(row["committed_units"] for row in before["load"]) > 0
    assert sum(row["committed_units"] for row in after["load"]) == 0
    main._intake_cached.cache_clear()


def test_model_selection_cannot_use_final_period_outcomes(monkeypatch):
    from types import SimpleNamespace
    series = synthetic_series()
    p = SimpleNamespace(cfg={"forecast": {"horizon_weeks": 17, "holdout_weeks": 17}}, factories=["F"])
    monkeypatch.setattr(fc, "intake_series", lambda planner: series)
    monkeypatch.setattr(fc, "MODEL_NAMES", ("stage_seasonal", "moving_average"))
    def predict(data, origin, horizon, model, train=None, targets=False):
        if train is not None and len(train):
            assert train.week.max() <= origin
        rows = fc._rows(data, origin, range(1, horizon+1), targets=True)
        level = data.loc[data.week <= origin, "units"].mean()
        return rows.assign(p50=level, actual=rows.target, used_model=model, fallback_reason="")
    monkeypatch.setattr(fc, "predict_model", predict)
    first = fc.backtest(p)
    series.loc[series.week >= 84, "units"] *= 100
    second = fc.backtest(p)
    pd.testing.assert_frame_equal(first["overall"], second["overall"])
    assert first["selected_model"] == second["selected_model"]
    assert not first["holdout_overall"].equals(second["holdout_overall"])


def test_displayed_factory_load_matches_final_decision_preview():
    import api.main as main
    seed = demo((1200, 1200))
    data = deepcopy(seed.data)
    data.tables["prs"].loc[1, "market_destination"] = "MX"
    p = Planner(data, deepcopy(seed.cfg)); p.plan_through("R2")
    displayed = main._current_load_fields(p, "R2", p.results["R2"].lots.copy())
    for row in displayed.itertuples():
        warning = fc.decision_warning(p, "R2", row.lot_id, intake=intake(qty=0))
        assert row.util_after_pct == pytest.approx(warning["committed_after_pct"], abs=.05)
        assert row.util_before_pct == pytest.approx(warning["committed_before_pct"], abs=.05)
