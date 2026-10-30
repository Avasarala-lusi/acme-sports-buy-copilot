"""Data health monitoring: flag unusual records in each MRP run's data load before they affect the plan.

Record checks run on every purchase requisition; run checks compare each load with the loads before it. Thresholds
live in the `data_health` config section. Nothing here changes the plan: flagged records are shown for review.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine.planner import Planner

CHECKS = {
    "unknown_article": ("error", "Article not in the article master"),
    "unknown_customer": ("error", "Customer not in the customer master"),
    "uncertified_factory": ("error", "Assigned to a factory not certified for the article"),
    "duplicate": ("error", "Same run, article, size, market, customer, RDD and quantity as another requisition"),
    "backup_flag_mismatch": ("info", "Backup flag does not match the assignment (flag set but the requisition stays at its primary, or the reverse)"),
    "lead_time_out_of_range": ("warning", "Manufacturing or transit lead time outside the factory's quoted range"),
    "qty_outlier": ("warning", "Quantity unusual for the article (robust z-score)"),
    "rdd_unreachable": ("warning", "RDD earlier than the run date plus the requisition's own lead times"),
    "rdd_far_out": ("info", "RDD unusually far from the run date"),
    "order_value_outlier": ("info", "Sales order value per unit unusual for the article (robust z-score)"),
}


def _robust_z(values: pd.Series, groups: pd.Series) -> pd.Series:
    med = values.groupby(groups).transform("median")
    mad = (values - med).abs().groupby(groups).transform("median") * 1.4826
    return ((values - med) / mad.replace(0, np.nan)).fillna(0.0)


def record_flags(planner: Planner) -> pd.DataFrame:
    """One row per (requisition, check) that fails."""
    cfg = planner.cfg.get("data_health", {})
    d = planner.data
    prs = d.prs.copy()
    f = d.factories.set_index("factory_id")
    flags: dict[str, pd.Series] = {}
    flags["unknown_article"] = ~prs["article_id"].isin(d.articles["article_id"])
    flags["unknown_customer"] = prs["customer_id"].notna() & ~prs["customer_id"].isin(d.customers["customer_id"])
    cert = d.cert_matrix.loc[d.cert_matrix["is_certified"], ["article_id", "factory_id"]]
    pairs = prs[["article_id", "assigned_factory"]].rename(columns={"assigned_factory": "factory_id"})
    flags["uncertified_factory"] = ~pairs.merge(cert, how="left", indicator=True)["_merge"].eq("both").to_numpy()
    key = ["run_id", "article_id", "size_id", "market_destination", "customer_id", "rdd_original", "requested_qty"]
    flags["duplicate"] = prs.duplicated(key, keep=False)
    flags["backup_flag_mismatch"] = (prs["assigned_factory"] != prs["primary_factory"]) != prs["backup_triggered"].astype(bool)
    fac = prs["assigned_factory"]
    mfg_lo, mfg_hi = fac.map(f["mfg_lt_min_days"]), fac.map(f["mfg_lt_max_days"])
    tr_lo, tr_hi = fac.map(f["trans_lt_min_days"]), fac.map(f["trans_lt_max_days"])
    flags["lead_time_out_of_range"] = ((prs["manufacturing_lead_time"] < mfg_lo) | (prs["manufacturing_lead_time"] > mfg_hi)
                                       | (prs["transportation_lead_time"] < tr_lo) | (prs["transportation_lead_time"] > tr_hi))
    z = _robust_z(prs["requested_qty"].astype(float), prs["article_id"])
    flags["qty_outlier"] = z.abs() > float(cfg.get("qty_robust_z", 5))
    lead = pd.to_timedelta(prs["manufacturing_lead_time"] + prs["transportation_lead_time"], unit="D")
    flags["rdd_unreachable"] = prs["rdd_original"] < prs["mrp_run_date"] + lead
    flags["rdd_far_out"] = (prs["rdd_original"] - prs["mrp_run_date"]).dt.days > int(cfg.get("rdd_horizon_days", 400))
    so = d.sales_orders.merge(prs[["pr_id", "article_id", "requested_qty"]], on="pr_id")
    so["per_unit"] = so["net_sales_value"] / so["requested_qty"].replace(0, np.nan)
    so_z = _robust_z(so["per_unit"].astype(float), so["article_id"])
    odd = set(so.loc[so_z.abs() > float(cfg.get("qty_robust_z", 5)), "pr_id"])
    flags["order_value_outlier"] = prs["pr_id"].isin(odd)

    detail = {
        "qty_outlier": lambda r: f"{r.requested_qty:,.0f} units (z {z[r.Index]:+.1f})",
        "lead_time_out_of_range": lambda r: f"{r.manufacturing_lead_time:.0f}+{r.transportation_lead_time:.0f} days at {r.assigned_factory}",
        "rdd_unreachable": lambda r: f"RDD {r.rdd_original:%Y-%m-%d}, run {r.mrp_run_date:%Y-%m-%d}",
        "rdd_far_out": lambda r: f"{(r.rdd_original - r.mrp_run_date).days} days out",
    }
    rows = []
    for check, mask in flags.items():
        sev, _ = CHECKS[check]
        hit = prs[np.asarray(mask, dtype=bool)]
        for r in hit.itertuples():
            rows.append({"pr_id": r.pr_id, "run_id": r.run_id, "article_id": r.article_id,
                         "market_destination": r.market_destination, "customer_id": r.customer_id,
                         "requested_qty": float(r.requested_qty), "check": check, "severity": sev,
                         "detail": detail[check](r) if check in detail else ""})
    return pd.DataFrame(rows, columns=["pr_id", "run_id", "article_id", "market_destination", "customer_id",
                                       "requested_qty", "check", "severity", "detail"])


def run_flags(planner: Planner) -> pd.DataFrame:
    """Per run: intake volume against earlier runs at the same season stage (demand swings about 12x between stages,
    so a plain trailing average would flag every season change). Falls back to the trailing median of 8 runs while a
    stage has fewer than two earlier runs."""
    from engine.forecast import intake_series

    cfg = planner.cfg.get("data_health", {})
    runs = planner.runs[["run_id", "week_number", "season"]].copy()
    vol = planner.data.prs.groupby("run_id").agg(records=("pr_id", "size"), units=("requested_qty", "sum"))
    runs = runs.merge(vol, on="run_id", how="left").fillna({"records": 0, "units": 0.0})
    stage = intake_series(planner).groupby("week")["stage"].first()
    runs["stage"] = runs["week_number"].map(stage).fillna("")
    expected = []
    for i, r in runs.iterrows():
        earlier = runs.iloc[:i]
        same = earlier.loc[(earlier["stage"] == r["stage"]) & (r["stage"] != ""), "units"]
        if len(same) >= 2:
            expected.append((float(same.median()), "same season stage"))
        elif len(earlier) >= 4:
            expected.append((float(earlier["units"].tail(8).median()), "trailing 8 runs"))
        else:
            expected.append((np.nan, ""))
    runs["expected_units"] = [e for e, _ in expected]
    runs["expected_basis"] = [b for _, b in expected]
    runs["volume_change_pct"] = (runs["units"] / runs["expected_units"] - 1) * 100
    limit = float(cfg.get("volume_change_pct", 60))
    runs["volume_flag"] = runs["volume_change_pct"].abs() > limit
    runs.loc[runs["records"] == 0, "volume_flag"] = True
    return runs


def health_report(planner: Planner, run_id: str | None = None, limit: int = 500) -> dict:
    flags = record_flags(planner)
    runs = run_flags(planner)
    serious = flags[flags["severity"] != "info"]
    per_run = (flags.groupby("run_id").agg(flagged_records=("pr_id", lambda s: s[serious.index.intersection(s.index)].nunique()),
                                           errors=("severity", lambda s: int((s == "error").sum())),
                                           warnings=("severity", lambda s: int((s == "warning").sum())),
                                           info=("severity", lambda s: int((s == "info").sum())))
               .reindex(runs["run_id"]).fillna(0).astype(int).reset_index())
    runs = runs.merge(per_run, on="run_id")
    runs["flagged_pct"] = np.where(runs["records"] > 0, runs["flagged_records"] / runs["records"].clip(lower=1) * 100, 0.0)
    n = len(planner.data.prs)
    checks = [{"check": c, "severity": sev, "description": desc,
               "records": int((flags["check"] == c).sum()), "share_pct": float((flags["check"] == c).sum()) / n * 100}
              for c, (sev, desc) in CHECKS.items()]
    out = {
        "records": n, "flagged_records": int(flags.loc[flags["severity"] != "info", "pr_id"].nunique()),
        "flagged_pct": float(flags.loc[flags["severity"] != "info", "pr_id"].nunique()) / n * 100 if n else 0.0,
        "runs_with_volume_flag": int(runs["volume_flag"].sum()),
        "checks": checks,
        "runs": runs.replace({np.nan: None}).to_dict("records"),
        "load_findings": list(planner.data.issues),
    }
    if run_id is not None:
        r = flags[flags["run_id"] == run_id]
        sev_order = {"error": 0, "warning": 1, "info": 2}
        r = r.assign(o=r["severity"].map(sev_order)).sort_values(["o", "check"]).drop(columns="o")
        row = runs[runs["run_id"] == run_id]
        out["run"] = {"run_id": run_id, **(row.iloc[0].replace({np.nan: None}).to_dict() if len(row) else {}),
                      "by_check": r.groupby("check").size().to_dict(), "flags": r.head(limit).to_dict("records")}
    return out
