"""Demand and load forecast: what the factories will have to make in the coming buying windows.

At a given MRP run the plan only knows the requisitions received so far. Requisitions keep arriving every week, and
on average they reach production about three months later, so the next four buying windows will carry load that is
not in the data yet. This module forecasts that unseen demand and turns it into expected factory load.

1. **Weekly intake per factory**: plannable units arriving per MRP week at each primary factory (wholesale demand
   without an order is left out, as Rule 5 moves it to Future).
2. **Forecast** of intake 1..H weeks ahead (H covers the look-ahead windows), using only weeks up to the run. Demand
   follows the buying stage in the MRP calendar (season type FW/SS x range version V1-V3, scheduled ahead), so the
   model is selected by a walk-forward backtest: the stage-aware seasonal model (this factory's average for the
   same stage in earlier seasons) wins on the current data and is the default; an Extra Trees model that learns a
   correction to it is kept as the challenger (`forecast.model` in the config). The P10-P90 range comes from the
   model's own past forecast errors, using only errors already known at the run.
3. **Load**: forecast intake is turned into production load with the release lags observed so far (weeks from
   arrival to release date), bought at the buying window of the release date, produced from that window's PO date
   over the factory's standard manufacturing time (article master defaults, as the client asked for demand that
   does not exist yet), spread by business days.

A walk-forward backtest compares the model with seasonal-naive, moving-average and gradient-boosting baselines.
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
    excluded = [exclusion.forecast_excluded(c, o, e) and not lc
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


def _gbm(seed: int = 0):
    from sklearn.ensemble import HistGradientBoostingRegressor
    return HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, random_state=seed)


def fit_predict(train: pd.DataFrame, test: pd.DataFrame, model: str = "stage_seasonal") -> pd.DataFrame:
    """Point forecast for the test rows."""
    out = test[["factory", "origin", "week", "horizon", "date"]].copy()
    if model == "stage_seasonal":  # same buying stage in earlier seasons
        out["p50"] = test["stage_mean"].to_numpy()
    elif model == "seasonal_naive":  # same week last year
        out["p50"] = np.where(test["has_lag52"] > 0, test["lag52"], test["mean8"])
    elif model == "moving_average":
        out["p50"] = test["mean4"].to_numpy()
    elif model in ("extra_trees", "gradient_boosting"):
        # learn the ratio of actual demand to the stage baseline, on weeks that have an earlier season to compare with
        rows = train[train["has_stage"] > 0]
        if len(rows) < 100:
            out["p50"] = test["stage_mean"].to_numpy()
        else:
            m = _extra_trees() if model == "extra_trees" else _gbm()
            m.fit(rows[FEATURES], rows["target"] / rows["stage_mean"].clip(lower=1.0))
            out["p50"] = (test["stage_mean"] * m.predict(test[FEATURES])).clip(lower=0).to_numpy()
    else:
        raise ValueError(f"unknown forecast model {model}")
    return out


BANDS = [(1, 4), (5, 8), (9, 99)]


def _band(h: int) -> int:
    return next(i for i, (lo, hi) in enumerate(BANDS) if lo <= h <= hi)


def error_ratios(series: pd.DataFrame, origin: int, horizon: int, model: str, first: int = 20) -> dict[int, np.ndarray]:
    """(actual + 1) / (forecast + 1) for past forecasts whose target week is already known at `origin`, per horizon
    band. Used for the P10-P90 range; nothing after the origin is used."""
    ratios: dict[int, list] = {i: [] for i in range(len(BANDS))}
    for o in range(first, origin):
        test = _rows(series, o, range(1, horizon + 1), True)
        test = test[(test["week"] <= origin)].dropna(subset=["target"])
        if test.empty:
            continue
        pred = fit_predict(test, test, "stage_seasonal" if model not in ("stage_seasonal", "seasonal_naive") else model)
        for h, a, f in zip(test["horizon"], test["target"], pred["p50"]):
            ratios[_band(int(h))].append((a + 1) / (f + 1))
    return {b: np.array(v) for b, v in ratios.items()}


def add_range(pred: pd.DataFrame, ratios: dict[int, np.ndarray]) -> pd.DataFrame:
    p10, p90 = [], []
    for h, f in zip(pred["horizon"], pred["p50"]):
        r = ratios.get(_band(int(h)), np.array([]))
        lo, hi = (np.quantile(r, 0.1), np.quantile(r, 0.9)) if len(r) >= 30 else (0.6, 1.4)
        p10.append(max(0.0, (f + 1) * lo - 1))
        p90.append(max(0.0, (f + 1) * hi - 1))
    return pred.assign(p10=p10, p90=p90)


def horizon_weeks(planner: Planner) -> int:
    return 4 * planner.cfg["buying_window"]["lookahead_windows"] + 1  # four windows ahead, about 17 weeks


def forecast_intake(planner: Planner, run_id: str) -> pd.DataFrame:
    """Intake forecast per factory for the weeks after `run_id`, using only weeks up to it."""
    series = intake_series(planner)
    origin = int(planner.runs.set_index("run_id").loc[run_id, "week_number"])
    H = horizon_weeks(planner)
    model = planner.cfg.get("forecast", {}).get("model", "stage_seasonal")
    test = _rows(series, origin, range(1, H + 1), targets=True)
    train = training_rows(series, origin, H) if model in ("extra_trees", "gradient_boosting") else test.iloc[0:0]
    out = add_range(fit_predict(train, test, model), error_ratios(series, origin, H, model))
    out["model"] = model
    out["has_stage"] = test["has_stage"].to_numpy()  # an earlier season of the same buying stage exists
    out["actual"] = test["target"].to_numpy()  # known later in the data; shown for comparison, never used to fit
    return out


# ---------------------------------------------------------------- load
def release_lag_weeks(planner: Planner, upto_week: int) -> dict[str, np.ndarray]:
    """Per factory, the share of units released 0..31 weeks after arriving (observed up to `upto_week`)."""
    prs = planner.prs[planner.prs["run_num"] < upto_week]
    lag = ((prs["release_primary"] - prs["mrp_run_date"]).dt.days // 7).clip(0, 31)
    out = {}
    for f in planner.factories.index:
        sel = prs["primary"] == f
        w = np.bincount(lag[sel].astype(int), weights=prs.loc[sel, "requested_qty"], minlength=32)[:32]
        out[f] = w / w.sum() if w.sum() else np.r_[np.zeros(13), 1.0, np.zeros(18)]
    return out


def standard_mfg_days(planner: Planner) -> dict[str, int]:
    """Article-master manufacturing time per primary factory (unit-weighted), for demand that does not exist yet."""
    art = planner.data.articles
    col = "manufacturing_lead_time" if "manufacturing_lead_time" in art else None
    out = {}
    for f in planner.factories.index:
        if col and (art["primary_factory"] == f).any():
            out[f] = int(round(art.loc[art["primary_factory"] == f, col].mean()))
        else:
            out[f] = int(round(planner.mid_lt[f][0]))
    return out


def forecast_load(planner: Planner, run_id: str, intake: pd.DataFrame | None = None):
    """Weekly load per factory over the look-ahead windows: committed + known open demand + forecast demand.

    Returns (weekly table, window table). Forecast units are placed with the observed release lags: released units
    are bought at the buying window of their release date (never before the next window after this run), and
    produced from that window's PO date.
    """
    from engine.pull_forward import _edges, projected_load

    planner.plan_through(run_id)
    r = planner.run_result(run_id)
    intake = forecast_intake(planner, run_id) if intake is None else intake
    origin = int(planner.runs.set_index("run_id").loc[run_id, "week_number"])
    known, _ = projected_load(planner, run_id)
    committed = planner.snapshots[run_id]
    lags = release_lag_weeks(planner, origin)
    mfg = standard_mfg_days(planner)
    first_window = pd.Timestamp(planner.calendar.after(r.buy_date)) if r.is_buying_run else r.buy_date

    p50, p90 = known.copy(), known.copy()
    for row in intake.itertuples():
        for lag, share in enumerate(lags[row.factory]):
            if share <= 0:
                continue
            release = row.date + pd.Timedelta(weeks=lag)
            window = max(pd.Timestamp(planner.calendar.on_or_before(release)), first_window)
            start = window  # client: production starts on the PO execution date of the buying window
            p50.add(row.factory, start, mfg[row.factory], row.p50 * share)
            p90.add(row.factory, start, mfg[row.factory], row.p90 * share)

    edges = _edges(planner, run_id)
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


# ---------------------------------------------------------------- backtest
def backtest(planner: Planner, first_origin: int = 40, step: int = 2) -> dict:
    """Walk-forward test: at each origin, use weeks up to it and forecast the next H weeks.

    Reports WAPE (sum of absolute errors / sum of actuals) per model and horizon band, and how often the actual
    falls inside the default model's P10-P90 range (built only from errors known at each origin).
    """
    series = intake_series(planner)
    H = horizon_weeks(planner)
    default = planner.cfg.get("forecast", {}).get("model", "stage_seasonal")
    models = ["stage_seasonal", "extra_trees", "gradient_boosting", "seasonal_naive", "moving_average"]
    last = int(series["week"].max())
    preds = []
    for origin in range(first_origin, last - 1, step):
        test = _rows(series, origin, range(1, H + 1), targets=True).dropna(subset=["target"])
        if test.empty:
            continue
        train = training_rows(series, origin, H)
        for model in models:
            pr = fit_predict(train, test, model)
            if model == default:
                pr = add_range(pr, error_ratios(series, origin, H, model))
            pr["actual"], pr["model"] = test["target"].to_numpy(), model
            preds.append(pr)
    df = pd.concat(preds, ignore_index=True)
    df["band"] = pd.cut(df["horizon"], [0, 4, 8, H], labels=["1-4 weeks", "5-8 weeks", f"9-{H} weeks"])

    def wape(g):
        return float((g["p50"] - g["actual"]).abs().sum() / max(g["actual"].sum(), 1.0) * 100)

    by_band = (df.groupby(["model", "band"], observed=True).apply(wape, include_groups=False)
               .rename("wape_pct").reset_index())
    overall = df.groupby("model").apply(wape, include_groups=False).rename("wape_pct").reset_index()
    d = df[df["model"] == default]
    coverage = float(((d["actual"] >= d["p10"]) & (d["actual"] <= d["p90"])).mean() * 100)
    return {"overall": overall.sort_values("wape_pct").reset_index(drop=True), "by_horizon": by_band,
            "coverage_pct": coverage, "default_model": default, "origins": int(df["origin"].nunique()),
            "horizon_weeks": H, "predictions": df}


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
        "overall": bt["overall"].to_dict("records"), "by_horizon": bt["by_horizon"].astype({"band": str}).to_dict("records"),
        "network_by_horizon": totals.groupby("horizon").apply(
            lambda g: float((g["p50"] - g["actual"]).abs().sum() / max(g["actual"].sum(), 1) * 100),
            include_groups=False).rename("wape_pct").reset_index().to_dict("records"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, default=float))
    return summary
