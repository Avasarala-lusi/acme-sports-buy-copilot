"""Advisory demand and factory-load forecasts, separate from purchase commitments.

Forecast eligible PR intake by primary factory using only demand known at the selected run and
an assumed-known buying-stage calendar. All eight methods share the same live/backtest dispatch.
A model's own past forecast errors calibrate its nominal range; missing history and fit failures
are explicit fallbacks. SARIMAX is AR(1) with stage regressors, not a fitted annual seasonal term.

The 17-week intake horizon is a team evaluation choice, separate from the four semi-monthly
load windows. Projected production cannot start before predicted PR intake. Future article-master
lead times and past eligible article mix estimate manufacturing duration. Known-open and forecast
load is unconstrained pressure, not capacity reservations. Saved planner decisions supply the
committed load. A proposal warning counts a lot once and does not mutate commitments.

Model selection uses earlier complete horizons. The final 17 weeks are excluded from selection
and reported separately. About 100 synthetic weeks provide limited evidence of annual repetition.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine.calendar import weeks_between, window_label
from engine.planner import Planner
from engine.rules import exclusion

FEATURES = ["horizon", "woy_sin", "woy_cos", "month", "last1", "mean4", "mean8", "lag52", "has_lag52",
            "lag52_ratio", "factory_code", "season_ss", "range_version", "weeks_into_stage", "stage_mean",
            "has_stage", "stage_ratio"]


# ---------------------------------------------------------------- data
def intake_series(planner: Planner) -> pd.DataFrame:
    """Plannable units arriving per MRP week (1..N) per primary factory, with the run date."""
    prs = planner.prs
    include_lc = planner.cfg["last_chance"].get("include_forecast_only", False)
    excluded = [exclusion.forecast_excluded(c, o, e) and not (lc and include_lc)
                for c, o, e, lc in zip(prs["channel_id"], prs["has_order"], prs["early_buy"], prs["last_chance"])]
    plan = prs[~np.array(excluded)]
    weeks = planner.runs[["run_id", "week_number", "mrp_freeze_datetime_utc", "season", "range_version"]].copy()
    weeks["date"] = pd.to_datetime(weeks["mrp_freeze_datetime_utc"]).dt.normalize()
    grid = pd.MultiIndex.from_product([weeks["week_number"], sorted(planner.factories.index)], names=["week", "factory"])
    units = (plan.assign(week=plan["run_id"].map(weeks.set_index("run_id")["week_number"]))
             .groupby(["week", "primary"])["requested_qty"].sum())
    units.index.names = ["week", "factory"]
    out = units.reindex(grid, fill_value=0.0).rename("units").reset_index()
    # buying stage from the MRP calendar, which is scheduled ahead: season type (FW/SS) and range version (V1-V3)
    weeks["season_ss"] = weeks["season"].str.startswith("SS").astype(float)
    weeks["range_version"] = weeks["range_version"].str[1:].astype(float)
    stage = weeks["season"] + weeks["range_version"].astype(str)
    weeks["weeks_into_stage"] = weeks.groupby((stage != stage.shift()).cumsum()).cumcount().astype(float)
    weeks["stage"] = weeks["season_ss"].astype(int).astype(str) + "-" + weeks["range_version"].astype(int).astype(str)
    cols = ["week_number", "date", "season_ss", "range_version", "weeks_into_stage", "stage"]
    return out.merge(weeks[cols].rename(columns={"week_number": "week"}), on="week")


def _week_date(known: pd.Series, week: int) -> pd.Timestamp:
    """Run date of an MRP week; weeks after the data continue weekly."""
    if week in known.index:
        return known[week]
    last = known.index.max()
    return known[last] + pd.Timedelta(weeks=week - last)


def _rows(series: pd.DataFrame, origin: int, horizons: range, targets: bool) -> pd.DataFrame:
    """Feature rows made at `origin` for target weeks origin+h. Only data up to the origin is used."""
    pivot = series.pivot(index="week", columns="factory", values="units")
    cal = series.drop_duplicates("week").set_index("week")
    dates = cal["date"]
    codes = {f: i for i, f in enumerate(pivot.columns)}
    hist = pivot.loc[:origin]
    rows = []
    for f in pivot.columns:
        s = hist[f]
        if len(s) < 1:
            continue
        last1, mean4, mean8 = s.iloc[-1], s.iloc[-4:].mean(), s.iloc[-8:].mean()
        for h in horizons:
            week = origin + h
            date = _week_date(dates, week)
            woy = date.isocalendar().week
            lag_week = week - 52
            has = lag_week in hist.index
            lag52 = float(hist.loc[lag_week, f]) if has else mean8
            # year-on-year level: the last 4 weeks against the same 4 weeks a year earlier
            ratio = (mean4 / max(float(hist.loc[origin - 55:origin - 52, f].mean()), 1.0)
                     if (origin - 52) in hist.index else 1.0)
            # same buying stage in earlier seasons (only weeks known at the origin)
            if week in cal.index:
                st = cal.loc[week]
                past = [w for w in cal.index[cal["stage"] == st["stage"]] if w <= origin and w < week - 8]
                stage_mean = float(hist.loc[past, f].mean()) if past else mean8
                cur = [w for w in cal.index[cal["stage"] == cal.loc[origin, "stage"]] if w <= origin]
                prev = [w for w in cal.index[cal["stage"] == cal.loc[origin, "stage"]] if w < min(cur) - 8] if cur else []
                stage_ratio = (float(hist.loc[cur, f].mean()) / max(float(hist.loc[prev, f].mean()), 1.0)) if prev else 1.0
                stage = {"season_ss": st["season_ss"], "range_version": st["range_version"],
                         "weeks_into_stage": st["weeks_into_stage"], "stage_mean": stage_mean,
                         "has_stage": float(bool(past)), "stage_ratio": stage_ratio}
            else:  # beyond the scheduled calendar
                stage = {"season_ss": -1.0, "range_version": -1.0, "weeks_into_stage": -1.0, "stage_mean": mean8,
                         "has_stage": 0.0, "stage_ratio": 1.0}
            row = {"factory": f, "factory_code": codes[f], "origin": origin, "week": week, "horizon": h, "date": date, **stage,
                   "woy_sin": np.sin(2 * np.pi * woy / 52), "woy_cos": np.cos(2 * np.pi * woy / 52), "month": date.month,
                   "last1": last1, "mean4": mean4, "mean8": mean8, "lag52": lag52, "has_lag52": float(has),
                   "lag52_ratio": ratio}
            if targets:
                row["target"] = float(pivot.loc[week, f]) if week in pivot.index else np.nan
            rows.append(row)
    return pd.DataFrame(rows)


def training_rows(series: pd.DataFrame, origin: int, horizon: int, min_origin: int = 8) -> pd.DataFrame:
    """Every (origin, horizon) example whose target week is already known at `origin` (no look-ahead)."""
    parts = [_rows(series, o, range(1, horizon + 1), True) for o in range(min_origin, origin)]
    data = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    return data[data["week"] <= origin].dropna(subset=["target"]) if len(data) else data


# ---------------------------------------------------------------- models
def _extra_trees(seed: int = 0):
    from sklearn.ensemble import ExtraTreesRegressor
    return ExtraTreesRegressor(n_estimators=300, min_samples_leaf=3, max_features=0.8, random_state=seed, n_jobs=-1)


def _random_forest(seed: int = 0):
    from sklearn.ensemble import RandomForestRegressor
    return RandomForestRegressor(n_estimators=300, min_samples_leaf=3, max_features=0.8, random_state=seed, n_jobs=-1)


def _xgboost(seed: int = 0):
    from xgboost import XGBRegressor
    return XGBRegressor(n_estimators=300, learning_rate=0.05, max_depth=4, subsample=0.8, colsample_bytree=0.8,
                        random_state=seed, n_jobs=4, verbosity=0)


def _gbm(seed: int = 0):
    from sklearn.ensemble import HistGradientBoostingRegressor
    return HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, random_state=seed)


def fit_predict(train: pd.DataFrame, test: pd.DataFrame, model: str = "stage_seasonal") -> pd.DataFrame:
    """Point forecast for the test rows."""
    out = test[["factory", "origin", "week", "horizon", "date"]].copy()
    out["used_model"], out["fallback_reason"] = model, ""
    if model == "stage_seasonal":  # same buying stage in earlier seasons
        out["p50"] = test["stage_mean"].to_numpy()
        missing = test["has_stage"].to_numpy() == 0
        out.loc[missing, "used_model"] = "moving_average_8"
        out.loc[missing, "fallback_reason"] = "No earlier matching stage; recent eight-week average"
    elif model == "seasonal_naive":  # same week last year
        out["p50"] = np.where(test["has_lag52"] > 0, test["lag52"], test["mean8"])
        missing = test["has_lag52"].to_numpy() == 0
        out.loc[missing, "used_model"] = "moving_average_8"
        out.loc[missing, "fallback_reason"] = "Same week last year unavailable; recent eight-week average"
    elif model == "moving_average":
        out["p50"] = test["mean4"].to_numpy()
    elif model in LEARNERS:
        # learn the ratio of actual demand to the stage baseline, on weeks that have an earlier season to compare with
        rows = train[train["has_stage"] > 0] if len(train) else train
        if len(rows) < 100:
            out["p50"] = test["stage_mean"].to_numpy()
            out["used_model"] = "stage_seasonal"
            out["fallback_reason"] = "Fewer than 100 training examples with earlier-stage history"
        else:
            m = LEARNERS[model]()
            m.fit(rows[FEATURES], rows["target"] / rows["stage_mean"].clip(lower=1.0))
            out["p50"] = (test["stage_mean"] * m.predict(test[FEATURES])).clip(lower=0).to_numpy()
    else:
        raise ValueError(f"unknown forecast model {model}")
    return out


LEARNERS = {"extra_trees": _extra_trees, "random_forest": _random_forest, "xgboost": _xgboost,
            "gradient_boosting": _gbm}
MODEL_NAMES = ("stage_seasonal", "extra_trees", "random_forest", "xgboost", "gradient_boosting",
               "sarimax", "seasonal_naive", "moving_average")


def sarimax_predict(series: pd.DataFrame, origin: int, horizon: int) -> pd.DataFrame:
    """SARIMAX per factory on log units up to the origin, with the buying stage (season type x range version, known
    in advance from the MRP calendar) as regressors. A seasonal ARIMA term with a 52-week period needs at least two
    full years before the origin, which 100 weeks never provide, so seasonality enters through the stage regressors."""
    import warnings

    from statsmodels.tsa.statespace.sarimax import SARIMAX

    cal = series.drop_duplicates("week").set_index("week").sort_index()
    stages = sorted(cal.loc[:origin, "stage"].unique())
    pivot = series.pivot(index="week", columns="factory", values="units").sort_index()
    weeks = list(range(origin + 1, origin + horizon + 1))
    future_stage = [cal.loc[w, "stage"] if w in cal.index else None for w in weeks]

    def dummies(stage_list):
        return pd.DataFrame([[1.0 if s == st else 0.0 for st in stages] for s in stage_list], columns=stages)

    x_hist = dummies(list(cal.loc[:origin, "stage"]))
    keep = [c for c in stages if x_hist[c].sum() > 0]  # stages seen so far; unseen ones fall back to the level
    rows = []
    for f in pivot.columns:
        y = np.log1p(pivot.loc[:origin, f].to_numpy(dtype=float))
        reason, fit_warning = "", ""
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                res = SARIMAX(y, exog=x_hist[keep].to_numpy()[:, 1:] if len(keep) > 1 else None, order=(1, 0, 0),
                              trend="c").fit(disp=False, maxiter=100)
                if not res.mle_retvals.get("converged", True):
                    raise ValueError("fit did not converge")
                xf = dummies(future_stage)[keep].to_numpy()[:, 1:] if len(keep) > 1 else None
                pred = np.expm1(res.forecast(steps=horizon, exog=xf)).clip(min=0)
                if not np.isfinite(pred).all():
                    raise ValueError("nonfinite prediction")
                fit_warning = "; ".join(dict.fromkeys(str(w.message) for w in caught))
        except (ValueError, np.linalg.LinAlgError, RuntimeError) as exc:
            pred = np.repeat(pivot.loc[:origin, f].tail(4).mean(), horizon)
            reason = f"SARIMAX fit failed: {exc}; four-week average used"
        rows += [{"factory": f, "week": w, "p50": float(v),
                  "used_model": "moving_average" if reason else "sarimax",
                  "fallback_reason": reason, "fit_warning": fit_warning} for w, v in zip(weeks, pred)]
    return pd.DataFrame(rows)


def predict_model(series, origin, horizon, model, train=None, targets=False):
    if model not in MODEL_NAMES:
        raise ValueError(f"unknown forecast model {model}")
    test = _rows(series, origin, range(1, horizon + 1), targets=targets)
    if model == "sarimax":
        out = test[["factory", "origin", "week", "horizon", "date"]].merge(
            sarimax_predict(series, origin, horizon), on=["factory", "week"], validate="one_to_one")
    else:
        if train is None:
            train = training_rows(series, origin, horizon) if model in LEARNERS else test.iloc[0:0]
        out = fit_predict(train, test, model)
    if targets:
        out["actual"] = test["target"].to_numpy()
    return out


def seasonality_tests(planner: Planner) -> dict:
    """Evidence that weekly demand is seasonal (client asked to prove it before choosing a method).

    - Seasonal strength from an STL decomposition with a 52-week period (Hyndman's F_s). Indicative only: with fewer
      than two full cycles in 100 weeks, STL can fit most of the series into the seasonal part.
    - Autocorrelation at the 52-week lag against its 95% significance bound.
    - Kruskal-Wallis test: does weekly demand differ between buying stages (season type x range version)?
    - Same test across calendar months.
    """
    from scipy.stats import kruskal
    from statsmodels.tsa.seasonal import STL
    from statsmodels.tsa.stattools import acf

    series = intake_series(planner)
    total = series.groupby("week").agg(units=("units", "sum"), stage=("stage", "first"), date=("date", "first"))
    y = np.log1p(total["units"].to_numpy(dtype=float))
    stl = STL(y, period=52, robust=True).fit()
    strength = max(0.0, 1 - np.var(stl.resid) / np.var(stl.seasonal + stl.resid))
    r = acf(y, nlags=52, fft=False)
    bound = 1.96 / np.sqrt(len(y))
    by_stage = [g["units"].to_numpy() for _, g in total.groupby("stage")]
    by_month = [g["units"].to_numpy() for _, g in total.groupby(total["date"].dt.month)]
    stage_means = total.groupby("stage")["units"].mean()
    return {
        "weeks": int(len(y)),
        "stl_seasonal_strength": float(strength),
        "acf_lag52": float(r[52]), "acf_bound_95": float(bound), "acf_lag52_significant": bool(abs(r[52]) > bound),
        "kruskal_stage_h": float(kruskal(*by_stage).statistic), "kruskal_stage_p": float(kruskal(*by_stage).pvalue),
        "kruskal_month_h": float(kruskal(*by_month).statistic), "kruskal_month_p": float(kruskal(*by_month).pvalue),
        "stage_mean_units": {k: float(v) for k, v in stage_means.items()},
        "stage_ratio_max_min": float(stage_means.max() / max(stage_means.min(), 1.0)),
    }


BANDS = [(1, 4), (5, 8), (9, 99)]


def _band(h: int) -> int:
    return next(i for i, (lo, hi) in enumerate(BANDS) if lo <= h <= hi)


def error_ratios(series: pd.DataFrame, origin: int, horizon: int, model: str, first: int = 20,
                 max_origins: int = 6, step: int = 4) -> dict[int, np.ndarray]:
    """(actual + 1) / (forecast + 1) for past forecasts whose target week is already known at `origin`, per horizon
    band. Used for the P10-P90 range; nothing after the origin is used."""
    ratios: dict[int, list] = {i: [] for i in range(len(BANDS))}
    for o in list(range(first, origin, step))[-max_origins:]:
        pred = predict_model(series, o, horizon, model, targets=True)
        pred = pred[(pred["week"] <= origin) & pred["actual"].notna()]
        if pred.empty:
            continue
        for h, a, f in zip(pred["horizon"], pred["actual"], pred["p50"]):
            ratios[_band(int(h))].append((a + 1) / (f + 1))
    return {b: np.array(v) for b, v in ratios.items()}


def add_range(pred: pd.DataFrame, ratios: dict[int, np.ndarray]) -> pd.DataFrame:
    p10, p90, counts = [], [], []
    for h, f in zip(pred["horizon"], pred["p50"]):
        r = ratios.get(_band(int(h)), np.array([]))
        lo, hi = (np.quantile(r, 0.1), np.quantile(r, 0.9)) if len(r) >= 30 else (0.6, 1.4)
        p10.append(max(0.0, (f + 1) * min(float(lo), 1.0) - 1))
        p90.append(max(float(f), (f + 1) * max(float(hi), 1.0) - 1))
        counts.append(len(r))
    return pred.assign(p10=p10, p90=p90, calibration_samples=counts,
        range_source=["past selected-model errors" if n >= 30 else
                      "assumed 60–140% range; insufficient past errors" for n in counts])


def horizon_weeks(planner: Planner) -> int:
    return int(planner.cfg.get("forecast", {}).get("horizon_weeks", 17))


def forecast_intake(planner: Planner, run_id: str, model: str | None = None) -> pd.DataFrame:
    """Intake forecast per factory for the weeks after `run_id`, using only weeks up to it."""
    series = intake_series(planner)
    origin = int(planner.runs.set_index("run_id").loc[run_id, "week_number"])
    H = horizon_weeks(planner)
    cfg = planner.cfg.get("forecast", {})
    model = model or cfg.get("model", "stage_seasonal")
    test = _rows(series, origin, range(1, H + 1), targets=False)
    out = add_range(predict_model(series, origin, H, model), error_ratios(series, origin, H, model,
        max_origins=int(cfg.get("calibration_origins", 6)), step=int(cfg.get("calibration_step", 4))))
    out["model"] = model
    out["has_stage"] = test["has_stage"].to_numpy()  # an earlier season of the same buying stage exists
    out["actual"] = np.nan  # future actuals belong only in the separate historical evaluation
    return out


# ---------------------------------------------------------------- load
def release_lag_weeks(planner: Planner, upto_week: int) -> dict[str, np.ndarray]:
    """Per factory, the share of units released 0..31 weeks after arriving (observed up to `upto_week`)."""
    week = planner.prs["run_id"].map(planner.runs.set_index("run_id")["week_number"])
    prs = planner.prs[week <= upto_week].copy()
    eligible = [not exclusion.forecast_excluded(c, o, e) or
                (lc and planner.cfg["last_chance"].get("include_forecast_only", False))
                for c, o, e, lc in zip(prs.channel_id, prs.has_order, prs.early_buy, prs.last_chance)]
    prs = prs[eligible]
    lag = ((prs["release_primary"] - prs["mrp_run_date"]).dt.days // 7).clip(0, 31)
    out = {}
    for f in planner.factories.index:
        sel = prs["primary"] == f
        w = np.bincount(lag[sel].astype(int), weights=prs.loc[sel, "requested_qty"], minlength=32)[:32]
        fallback = np.zeros(32)
        fallback[min(31, max(0, int(planner.cfg.get("forecast", {}).get("default_release_lag_weeks", 13))))] = 1.0
        out[f] = w / w.sum() if w.sum() else fallback
    return out


def standard_mfg_days(planner: Planner, upto_week: int | None = None) -> dict[str, float]:
    """Article-master manufacturing time per primary factory (unit-weighted), for demand that does not exist yet."""
    art = planner.data.articles
    col = "manufacturing_lead_time" if "manufacturing_lead_time" in art else None
    known = planner.prs
    if upto_week is not None:
        week = known["run_id"].map(planner.runs.set_index("run_id")["week_number"])
        known = known[week <= upto_week]
    mask = [not exclusion.forecast_excluded(c, o, e) or
            (lc and planner.cfg["last_chance"].get("include_forecast_only", False))
            for c, o, e, lc in zip(known.channel_id, known.has_order, known.early_buy, known.last_chance)]
    known = known[mask]
    weights = known.groupby("article_id")["requested_qty"].sum()
    out = {}
    for f in planner.factories.index:
        if col and (art["primary_factory"] == f).any():
            articles = art.loc[art["primary_factory"] == f]
            mix = articles["article_id"].map(weights).fillna(0).to_numpy()
            out[f] = float(np.average(articles[col], weights=mix) if mix.sum() else articles[col].mean())
        else:
            out[f] = float(planner.mid_lt[f][0])
    return out


def _load_ledgers(planner: Planner, run_id: str, intake: pd.DataFrame | None = None):
    """Weekly load per factory over the look-ahead windows: committed + known open demand + forecast demand.

    Returns independent committed/known/central/upper ledgers and traceable forecast components.
    Hypothetical purchases respect both the predicted intake date and the next available window.
    """
    from engine.pull_forward import projected_load

    planner.plan_through(run_id)
    r = planner.run_result(run_id)
    intake = forecast_intake(planner, run_id) if intake is None else intake
    origin = int(planner.runs.set_index("run_id").loc[run_id, "week_number"])
    known, _ = projected_load(planner, run_id)
    committed = planner.snapshots[run_id]
    if not r.is_buying_run:
        # A weekly draft previews purchases, but does not reserve capacity.
        # Keep those units in known-open pressure, not committed production.
        from engine.capacity import CapacityLedger
        prior = [x for key, x in planner.results.items() if x.is_buying_run and
                 planner.run_index[key] < planner.run_index[run_id]]
        committed = (planner.snapshots[prior[-1].run_id] if prior else
                     CapacityLedger(planner.factories["weekly_capacity_units"].to_dict(),
                                    planner.cfg["capacity"]["spread_over_manufacturing"]))
    lags = release_lag_weeks(planner, origin)
    mfg = standard_mfg_days(planner, origin)
    first_window = pd.Timestamp(planner.calendar.after(r.buy_date)) if r.is_buying_run else r.buy_date

    p50, p90 = known.copy(), known.copy()
    components = []
    for row in intake.itertuples():
        for lag, share in enumerate(lags[row.factory]):
            if share <= 0:
                continue
            release = row.date + pd.Timedelta(weeks=lag)
            window = max(pd.Timestamp(planner.calendar.on_or_before(release)),
                         pd.Timestamp(planner.calendar.on_or_after(row.date)), first_window)
            start = window  # client: production starts on the PO execution date of the buying window
            p50.add(row.factory, start, mfg[row.factory], row.p50 * share)
            p90.add(row.factory, start, mfg[row.factory], row.p90 * share)
            components.append({"factory": row.factory, "intake_date": row.date, "production_start": start,
                               "mfg_days": mfg[row.factory], "p50": row.p50 * share, "p90": row.p90 * share})

    return committed.copy(), known, p50, p90, components


def forecast_load(planner: Planner, run_id: str, intake: pd.DataFrame | None = None):
    """Saved commitments plus known-open and forecast demand; forecast load is advisory only."""
    committed, known, p50, p90, _ = _load_ledgers(planner, run_id, intake)
    result = planner.run_result(run_id)
    start = planner.calendar.after(result.buy_date) if result.is_buying_run else result.buy_date
    edges = [pd.Timestamp(d) for d in planner.calendar.windows_from(
        start, int(planner.cfg["buying_window"]["lookahead_windows"]))]
    weeks = sorted({w for i in range(len(edges) - 1) for w in weeks_between(edges[i], edges[i + 1])})
    rows = []
    for f, cap in planner.factories["weekly_capacity_units"].items():
        for w in weeks:
            c, k, m, h = (committed.units[f].get(w, 0.0), known.units[f].get(w, 0.0),
                          p50.units[f].get(w, 0.0), p90.units[f].get(w, 0.0))
            rows.append({"factory_id": f, "week": pd.Timestamp(w), "capacity": cap,
                         "committed_units": c, "known_open_units": k - c, "forecast_units": m - k,
                         "known_pct": k / cap * 100, "forecast_pct": m / cap * 100, "forecast_p90_pct": h / cap * 100})
    weekly = pd.DataFrame(rows)

    threshold = planner.cfg["capacity"]["backup_threshold_pct"]
    win = []
    for i in range(len(edges) - 1):
        ws = [pd.Timestamp(w) for w in weeks_between(edges[i], edges[i + 1])]
        for f in planner.factories.index:
            g = weekly[(weekly["factory_id"] == f) & weekly["week"].isin(ws)]
            if g.empty:
                continue
            known_peak, fc_peak, p90_peak = g["known_pct"].max(), g["forecast_pct"].max(), g["forecast_p90_pct"].max()
            win.append({"window": window_label(edges[i]), "factory_id": f, "known_peak_pct": known_peak,
                        "forecast_peak_pct": fc_peak, "p90_peak_pct": p90_peak,
                        "early_warning": bool(known_peak < threshold <= fc_peak),
                        "forecast_units": float(g["forecast_units"].sum())})
    return weekly, pd.DataFrame(win)


def decision_warning(planner, run_id, lot_id, factory=None, intake=None):
    """Preview this lot once at the proposed factory; never commit a forecast or reserve capacity."""
    planner.plan_through(run_id)
    result = planner.run_result(run_id)
    matches = result.lots[result.lots["lot_id"] == lot_id]
    if len(matches) != 1:
        raise ValueError("Unknown current-run lot; refresh the plan")
    lot = matches.iloc[0]
    factory = factory or lot.assigned_factory
    if factory not in planner.certified[lot.article_id]:
        raise ValueError("Factory is not certified for this article")
    committed, known, median, high, _ = _load_ledgers(planner, run_id, intake)
    ledgers = (committed, known, median, high)
    decision = lot.get("decision", lot.auto_decision)
    ids = list(filter(None, lot.pr_ids.split(",")))
    if not ids:
        raise ValueError("No units remain in this lot")
    if decision == "Buy":
        for ledger in ledgers:
            ledger.remove(lot.assigned_factory, lot.production_start, lot.mfg_days, lot.consolidated_qty)
    else:
        from engine.pull_forward import projected_load
        _, open_prs = projected_load(planner, run_id)
        for pr in open_prs[open_prs.pr_id.isin(ids)].itertuples():
            for ledger in (known, median, high):
                ledger.remove(pr.primary, pr.start, pr.mfg, pr.requested_qty)
    m, _ = planner.lot_lead_times(ids, factory)
    cap = float(planner.factories.loc[factory, "weekly_capacity_units"])
    before = committed.utilization(factory, committed.weeks_for(result.buy_date, m))
    after = committed.utilization_with(factory, result.buy_date, m, lot.consolidated_qty)
    for ledger in ledgers:
        ledger.add(factory, result.buy_date, m, lot.consolidated_qty)
    rows = []
    for week in committed.weeks_for(result.buy_date, m):
        c, k, f, hi = [ledger.units[factory].get(week, 0.0) / cap * 100 for ledger in ledgers]
        rows.append({"week": pd.Timestamp(week), "committed_after_pct": c, "known_after_pct": k,
                     "forecast_after_pct": f, "forecast_p90_pct": hi})
    threshold = float(planner.cfg["capacity"]["backup_threshold_pct"])
    return {"run_id": run_id, "lot_id": lot_id, "factory_id": factory,
            "model": str(intake.model.iloc[0]) if intake is not None else planner.cfg["forecast"]["model"],
            "committed_before_pct": before, "committed_after_pct": after,
            "hard_capacity_blocked": after > planner.cfg["capacity"]["hard_limit_pct"],
            "forecast_warning": any(r["forecast_after_pct"] >= threshold and
                                    r["forecast_after_pct"] > r["known_after_pct"] + 1e-6 for r in rows),
            "threshold_pct": threshold, "weeks": rows,
            "basis": "Saved planner decisions; forecast is advisory and reserves no capacity"}


# ---------------------------------------------------------------- backtest
def backtest(planner: Planner, first_origin: int = 40, step: int | None = None) -> dict:
    """Select on earlier complete horizons; reserve the final H weeks for evaluation only."""
    series = intake_series(planner)
    cfg = planner.cfg.get("forecast", {})
    h = horizon_weeks(planner)
    last = int(series.week.max())
    holdout = int(cfg.get("holdout_weeks", h))
    if holdout != h:
        raise ValueError("For one final forecast origin, holdout_weeks must equal horizon_weeks")
    split = last - holdout
    step = step or int(cfg.get("backtest_step", 4))
    default = cfg.get("model", "stage_seasonal")
    origins = list(range(first_origin, split - h + 1, step))
    if not origins or split < 8:
        raise ValueError("Not enough history for a separate selection and final evaluation period")
    parts = []
    failures = []
    for origin, period in [(o, "selection") for o in origins] + [(split, "holdout")]:
        train = training_rows(series, origin, h)
        for model in MODEL_NAMES:
            try:
                pred = predict_model(series, origin, h, model, train=train, targets=True)
                pred = pred[(pred.week <= last) & pred.actual.notna()].copy()
                if model == default:
                    pred = add_range(pred, error_ratios(series, origin, h, model,
                        max_origins=int(cfg.get("calibration_origins", 6)),
                        step=int(cfg.get("calibration_step", 4))))
                pred["model"], pred["period"] = model, period
                parts.append(pred)
            except (ImportError, RuntimeError, ValueError) as exc:
                failures.append({"model": model, "origin": origin, "period": period, "error": str(exc)})
    if not parts:
        raise ValueError("No model produced an evaluation forecast")
    df = pd.concat(parts, ignore_index=True)
    df["band"] = df.horizon.map(lambda x: "1-4 weeks" if x <= 4 else "5-8 weeks" if x <= 8 else f"9-{h} weeks")
    def wape(g):
        return float((g.p50-g.actual).abs().sum()/max(g.actual.sum(), 1.0)*100)
    selection = df[df.period == "selection"]
    final = df[df.period == "holdout"]
    def summary(data):
        rows = []
        for model, group in data.groupby("model"):
            # Incomplete models are visible as failures, never ranked as winners.
            expected = len(data.origin.unique()) * h * len(planner.factories)
            rows.append({"model": model, "wape_pct": wape(group),
                         "complete": len(group) == expected,
                         "fallback_pct": float(group.fallback_reason.ne("").mean()*100)})
        return pd.DataFrame(rows).sort_values("wape_pct").reset_index(drop=True)
    overall, final_overall = summary(selection), summary(final)
    complete = overall[overall.complete]
    selected = str(complete.iloc[0].model) if len(complete) else None
    d = final[final.model == default]
    coverage = float(((d.actual >= d.p10) & (d.actual <= d.p90)).mean()*100) if len(d) else None
    by_band = selection.groupby(["model", "band"]).apply(wape, include_groups=False).rename("wape_pct").reset_index()
    return {"overall": overall, "holdout_overall": final_overall, "by_horizon": by_band,
            "coverage_pct": coverage, "default_model": default, "selected_model": selected,
            "origins": len(origins), "selection_last_week": split, "holdout_first_week": split+1,
            "holdout_last_week": last, "horizon_weeks": h, "predictions": df, "failures": failures,
            "evaluation_note": "Winner chosen using selection periods only; final-period errors are reported separately."}


def cached_backtest(planner: Planner) -> dict:
    """The backtest takes about a minute; keep its summary next to the planned engine (same cache key)."""
    import json

    from engine.config import ROOT
    from engine.output import _config_hash

    path = ROOT / planner.cfg["data"]["output_dir"] / f"forecast_backtest_{_config_hash(planner.cfg)}.json"
    if path.exists():
        return json.loads(path.read_text())
    bt = backtest(planner)
    totals = (bt["predictions"][bt["predictions"]["model"] == bt["default_model"]]
              .groupby(["origin", "horizon"])[["p50", "actual"]].sum().reset_index())
    summary = {
        "default_model": bt["default_model"], "coverage_pct": bt["coverage_pct"], "origins": bt["origins"],
        "horizon_weeks": bt["horizon_weeks"],
        "selected_model": bt["selected_model"], "holdout_first_week": bt["holdout_first_week"],
        "holdout_last_week": bt["holdout_last_week"], "selection_last_week": bt["selection_last_week"],
        "holdout_overall": bt["holdout_overall"].to_dict("records"),
        "failures": bt["failures"], "evaluation_note": bt["evaluation_note"],
        "overall": bt["overall"].to_dict("records"), "by_horizon": bt["by_horizon"].astype({"band": str}).to_dict("records"),
        "network_by_horizon": totals.groupby("horizon").apply(
            lambda g: float((g["p50"] - g["actual"]).abs().sum() / max(g["actual"].sum(), 1) * 100),
            include_groups=False).rename("wape_pct").reset_index().to_dict("records"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, default=float))
    return summary
