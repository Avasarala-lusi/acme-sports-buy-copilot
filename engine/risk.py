"""On-time probability: how likely each lot is to arrive by its requested dates when lead times vary.

The planned lead times are what the requisition (or the factory midpoint) quotes. The realised lead time is the plan
plus a delay drawn from a triangular distribution sized by the factory's quoted range (fact: every factory publishes a
min-max range for manufacturing and for transit). By default a lot can finish up to 25% of the range early and run up to
50% of the range late, so delays are larger than gains (`risk` in the config). One delay is drawn per lot, so all
requisitions in a lot arrive together.

The delay distribution depends only on the factory, so the probability that a requisition arrives on time is the
factory's delay CDF evaluated at its planned slack (RDD minus planned arrival). That makes it exact for a given
distribution, repeatable, and fast enough for the optimiser to use on every option.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine.planner import Planner

BANDS = [(0.0, 0.5, "below 50%"), (0.5, 0.8, "50-80%"), (0.8, 0.95, "80-95%"), (0.95, 1.01, "95% or more")]


class DelayModel:
    """Total delay (manufacturing + transit, days) per factory, as sorted simulated draws."""

    def __init__(self, planner: Planner):
        cfg = planner.cfg.get("risk", {})
        n = int(cfg.get("simulations", 20000))
        early, late = float(cfg.get("early_share_of_range", 0.25)), float(cfg.get("late_share_of_range", 0.5))
        rng = np.random.default_rng(int(cfg.get("seed", 7)))
        self.draws: dict[str, np.ndarray] = {}
        for f, r in planner.factories.iterrows():
            total = np.zeros(n)
            for lo, hi in [("mfg_lt_min_days", "mfg_lt_max_days"), ("trans_lt_min_days", "trans_lt_max_days")]:
                width = float(r[hi] - r[lo])
                total += rng.triangular(-early * width, 0.0, late * width, n) if width > 0 else 0.0
            self.draws[f] = np.sort(total)

    def p_on_time(self, factory, slack_days) -> np.ndarray:
        """P(delay <= slack) for each requisition; factory and slack are aligned arrays (or a scalar factory)."""
        slack = np.asarray(slack_days, dtype=float)
        factories = np.broadcast_to(np.asarray(factory, dtype=object), slack.shape)
        out = np.empty(slack.shape)
        for f in pd.unique(factories.ravel()):
            m = factories == f
            d = self.draws[f]
            out[m] = np.searchsorted(d, slack[m], side="right") / len(d)
        return out

    def quantile(self, factory: str, q: float) -> float:
        return float(np.quantile(self.draws[factory], q))


def _pr_rows(planner: Planner, lots: pd.DataFrame) -> pd.DataFrame:
    """One row per requisition in the lots, with its planned slack (RDD minus planned arrival, days)."""
    rows = lots[["lot_id", "pr_ids", "assigned_factory", "production_start", "mfg_days", "trans_days"]].copy()
    rows["pr_id"] = rows["pr_ids"].str.split(",")
    rows = rows.explode("pr_id")
    arrival = (pd.to_datetime(rows["production_start"])
               + pd.to_timedelta(rows["mfg_days"] + rows["trans_days"], unit="D")).dt.normalize()
    rows["qty"] = rows["pr_id"].map(lambda p: planner.rows[p]["requested_qty"]).astype(float)
    rows["nsv"] = rows["pr_id"].map(lambda p: planner.rows[p]["nsv"]).astype(float)
    rows["rdd"] = rows["pr_id"].map(lambda p: planner.rows[p]["rdd_original"])
    rows["slack"] = (pd.to_datetime(rows["rdd"]) - arrival).dt.days.astype(float)
    return rows


def lot_risk(planner: Planner, lots: pd.DataFrame | None = None, model: DelayModel | None = None) -> pd.DataFrame:
    """Per lot: unit-weighted on-time probability, expected on-time units and sales value at risk."""
    lots = planner.bought_lots() if lots is None else lots
    model = model or DelayModel(planner)
    if not len(lots):
        return pd.DataFrame()
    rows = _pr_rows(planner, lots)
    rows["p"] = model.p_on_time(rows["assigned_factory"].to_numpy(), rows["slack"].to_numpy())
    rows["exp_units"] = rows["qty"] * rows["p"]
    rows["nsv_risk"] = rows["nsv"] * (1 - rows["p"])
    g = rows.groupby("lot_id").agg(units=("qty", "sum"), expected_on_time_units=("exp_units", "sum"),
                                   nsv_at_risk_usd=("nsv_risk", "sum"), min_slack_days=("slack", "min"))
    g["p_on_time"] = g["expected_on_time_units"] / g["units"]
    keep = ["lot_id", "run_id", "buying_window", "article_id", "market_destination", "assigned_factory",
            "consolidated_qty", "on_time", "on_time_units", "nsv_usd", "suggested_rdd", "earliest_rdd"]
    return lots[keep].merge(g.reset_index(), on="lot_id")


def _band(p: float) -> str:
    return next(label for lo, hi, label in BANDS if lo <= p < hi)


def risk_report(planner: Planner, run_id: str | None = None, top: int = 200) -> dict:
    """On-time probability of the bought plan (or one buying run): summary, bands, factories and riskiest lots."""
    model = DelayModel(planner)
    lots = planner.bought_lots()
    if run_id is not None:
        lots = lots[lots["run_id"] == run_id]
    r = lot_risk(planner, lots, model)
    if not len(r):
        return {"run_id": run_id, "lots": 0, "units": 0.0, "bands": [], "by_factory": [], "riskiest": [],
                "factories": []}
    units = float(r["units"].sum())
    nsv = float(r["nsv_usd"].sum())
    r["band"] = r["p_on_time"].map(_band)
    bands = r.groupby("band").agg(lots=("lot_id", "size"), units=("units", "sum"))
    by_f = r.groupby("assigned_factory").agg(units=("units", "sum"), planned=("on_time_units", "sum"),
                                             expected=("expected_on_time_units", "sum"),
                                             nsv_at_risk_usd=("nsv_at_risk_usd", "sum")).reset_index()
    by_f["planned_on_time_pct"] = by_f["planned"] / by_f["units"] * 100
    by_f["expected_on_time_pct"] = by_f["expected"] / by_f["units"] * 100
    cfg = planner.cfg.get("risk", {})
    factories = [{"factory_id": f, "delay_p10_days": model.quantile(f, 0.1), "delay_p50_days": model.quantile(f, 0.5),
                  "delay_p90_days": model.quantile(f, 0.9)} for f in planner.factories.index]
    riskiest = r.sort_values("nsv_at_risk_usd", ascending=False).head(top)
    return {
        "run_id": run_id, "lots": int(len(r)), "units": units,
        "planned_on_time_pct": float(r["on_time_units"].sum()) / units * 100,
        "expected_on_time_pct": float(r["expected_on_time_units"].sum()) / units * 100,
        "expected_on_time_units": float(r["expected_on_time_units"].sum()),
        "nsv_usd": nsv, "nsv_at_risk_usd": float(r["nsv_at_risk_usd"].sum()),
        "value_weighted_on_time_pct": (1 - float(r["nsv_at_risk_usd"].sum()) / nsv) * 100 if nsv else 0.0,
        "planned_on_time_but_at_risk_lots": int(((r["on_time"]) & (r["p_on_time"] < 0.8)).sum()),
        "assumption": {"early_share_of_range": cfg.get("early_share_of_range", 0.25),
                       "late_share_of_range": cfg.get("late_share_of_range", 0.5)},
        "bands": [{"band": b, "lots": int(bands["lots"].get(b, 0)), "units": float(bands["units"].get(b, 0))}
                  for *_, b in BANDS],
        "by_factory": by_f.drop(columns=["planned", "expected"]).to_dict("records"),
        "factories": factories,
        "riskiest": riskiest.drop(columns=["band"]).to_dict("records"),
    }
