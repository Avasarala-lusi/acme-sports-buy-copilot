"""Demand and load forecast: no look-ahead, sensible ranges, and the backtest."""
import numpy as np
import pytest

from engine import forecast as fc
from tests.conftest import needs_data

pytestmark = needs_data
RUN = "MRP-WK020"


def test_features_use_only_weeks_up_to_the_origin(planner):
    series = fc.intake_series(planner)
    origin = 60
    a = fc._rows(series, origin, range(1, 18), targets=False)
    scrambled = series.astype({"units": float})
    future = scrambled["week"] > origin
    scrambled.loc[future, "units"] = np.random.default_rng(0).uniform(0, 1e6, future.sum())
    b = fc._rows(scrambled, origin, range(1, 18), targets=False)
    assert np.allclose(a[fc.FEATURES].to_numpy(float), b[fc.FEATURES].to_numpy(float))


def test_training_rows_never_see_the_future(planner):
    series = fc.intake_series(planner)
    rows = fc.training_rows(series, 50, 17)
    assert len(rows) and (rows["week"] <= 50).all() and (rows["origin"] < 50).all()


def test_forecast_ranges_are_ordered(planner):
    out = fc.forecast_intake(planner, RUN)
    assert len(out) == 6 * fc.horizon_weeks(planner)
    assert (out["p10"] <= out["p50"] + 1e-9).all() and (out["p50"] <= out["p90"] + 1e-9).all()
    assert out["week"].min() == 21  # starts the week after the run


def test_load_forecast_adds_unseen_demand(planner):
    weekly, windows = fc.forecast_load(planner, RUN)
    assert (weekly["forecast_units"] >= -1e-6).all()
    assert (weekly["forecast_pct"] >= weekly["known_pct"] - 1e-6).all()
    assert windows["early_warning"].dtype == bool and set(windows["factory_id"]) == set(planner.factories.index)


def test_backtest_picks_a_model_that_beats_the_naive_level(planner):
    bt = fc.backtest(planner, first_origin=40, step=10)
    overall = bt["overall"].set_index("model")["wape_pct"]
    assert overall[bt["default_model"]] <= overall["moving_average"]
    assert 0 <= bt["coverage_pct"] <= 100


def test_demand_is_seasonal(planner):
    t = fc.seasonality_tests(planner)
    assert t["acf_lag52_significant"] and t["kruskal_stage_p"] < 0.01 and t["stage_ratio_max_min"] > 2


def test_sarimax_forecasts_every_factory_and_week(planner):
    series = fc.intake_series(planner)
    out = fc.sarimax_predict(series, 60, 17)
    assert len(out) == 6 * 17 and (out["p50"] >= 0).all()
