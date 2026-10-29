"""Who is affected when the plan delivers late, and how much it is worth (client, Oct 29 2026).

Scope is firm demand: every requisition except wholesale forecasts without an order (Rule 5, Future) and demand
still open at the end of the data. Each requisition is either delivered on time, delivered late, or not bought
(left with the planner: review or unresolved). The baseline is the client's: every requisition bought at its
supplied factory with its own lead times, starting on the PO date of the run it appeared in.

Value at risk is measured two ways:
- the client's average price per unit ($21 by default, `impact.price_per_unit_usd`; $19-22 shown as a range), and
- the actual net sales value of the requisition's sales order where one exists (the price is used otherwise).
"""
from __future__ import annotations

import pandas as pd

from engine.planner import BOUGHT, FUTURE_FORECAST, OPEN, Planner

LATE_BANDS = [(1, 7, "1-7 days"), (8, 30, "8-30 days"), (31, 60, "31-60 days"), (61, 10_000, "over 60 days")]


def price_per_unit(planner: Planner) -> float:
    return float(planner.cfg.get("impact", {}).get("price_per_unit_usd", 21.0))


def requisition_status(planner: Planner) -> pd.DataFrame:
    """One row per firm requisition: baseline and plan arrival, lateness and value."""
    out = planner.pr_outcomes()
    firm = out[~out["outcome"].isin([FUTURE_FORECAST, OPEN])].set_index("pr_id")
    prs = planner.prs.loc[firm.index]

    po = prs["run_id"].map(planner.runs.set_index("run_id")["po_execution_date"]).map(pd.Timestamp)
    lead = pd.to_timedelta(prs["manufacturing_lead_time"] + prs["transportation_lead_time"], unit="D")
    base_arrival = (po + lead).dt.normalize()

    lots = planner.bought_lots()
    arrival = (lots.assign(pr_id=lots["pr_ids"].str.split(",")).explode("pr_id")
               .set_index("pr_id")["suggested_rdd"]) if len(lots) else pd.Series(dtype="datetime64[ns]")
    plan_arrival = firm.index.to_series().map(arrival)

    rdd = prs["rdd_original"]
    df = pd.DataFrame({
        "pr_id": firm.index, "units": prs["requested_qty"].to_numpy(), "rdd": rdd.to_numpy(),
        "market": prs["market_destination"].to_numpy(), "category": prs["category"].to_numpy(),
        "product_line": prs["article_id"].str.split("-").str[0].to_numpy(),
        "article_id": prs["article_id"].to_numpy(), "customer_id": prs["customer_id"].to_numpy(),
        "channel": prs["channel_id"].map({"01": "Wholesale", "02": "DTC"}).to_numpy(),
        "nsv": prs["nsv"].to_numpy(), "outcome": firm["outcome"].to_numpy(),
        "baseline_factory": prs["assigned_factory"].to_numpy(),
        "baseline_days_late": (base_arrival - rdd).dt.days.clip(lower=0).to_numpy(),
        "plan_days_late": (plan_arrival.to_numpy() - rdd.to_numpy()) / pd.Timedelta(days=1),
    })
    df["plan_days_late"] = df["plan_days_late"].clip(lower=0)
    df["baseline_status"] = (df["baseline_days_late"] > 0).map({True: "late", False: "on time"})
    df["plan_status"] = "not bought (planner)"
    bought = df["outcome"] == BOUGHT
    df.loc[bought, "plan_status"] = (df.loc[bought, "plan_days_late"] > 0).map({True: "late", False: "on time"})
    price = price_per_unit(planner)
    df["value_usd"] = df["nsv"].where(df["nsv"] > 0, df["units"] * price)
    cust = planner.data.customers.set_index("customer_id")
    df["customer"] = df["customer_id"].map(cust["name"]).fillna(df["customer_id"])
    df["segment"] = df["customer_id"].map(cust["segment"]).fillna("")
    return df


def _band(days: float) -> str:
    return next((label for lo, hi, label in LATE_BANDS if lo <= days <= hi), "")


def impact_report(planner: Planner, price: float | None = None) -> dict:
    """Summary and breakdowns of late and undelivered demand, plan vs baseline."""
    df = requisition_status(planner)
    price = price_per_unit(planner) if price is None else float(price)
    total = float(df["units"].sum())

    def summary(status_col: str) -> dict:
        g = df.groupby(status_col)
        units = g["units"].sum().to_dict()
        value = g["value_usd"].sum().to_dict()
        return {s: {"units": float(units.get(s, 0)), "share_pct": float(units.get(s, 0)) / total * 100,
                    "usd_at_price": float(units.get(s, 0)) * price, "usd_order_value": float(value.get(s, 0))}
                for s in ["on time", "late", "not bought (planner)"] if s in units}

    def by(dim: str, top: int | None = None) -> list[dict]:
        rows = []
        for key, g in df.groupby(dim):
            base_late = float(g.loc[g["baseline_status"] == "late", "units"].sum())
            plan_late = float(g.loc[g["plan_status"] == "late", "units"].sum())
            not_bought = float(g.loc[g["plan_status"] == "not bought (planner)", "units"].sum())
            units = float(g["units"].sum())
            rows.append({dim: key, "units": units,
                         "baseline_on_time_pct": (units - base_late) / units * 100 if units else 0.0,
                         "plan_on_time_pct": float(g.loc[g["plan_status"] == "on time", "units"].sum()) / units * 100 if units else 0.0,
                         "plan_late_units": plan_late, "not_bought_units": not_bought,
                         "extra_late_or_unbought_units": plan_late + not_bought - base_late,
                         "usd_at_price": (plan_late + not_bought - base_late) * price,
                         "plan_median_days_late": float(g.loc[g["plan_status"] == "late", "plan_days_late"].median())
                         if (g["plan_status"] == "late").any() else 0.0})
        rows.sort(key=lambda r: -r["extra_late_or_unbought_units"])
        return rows[:top] if top else rows

    late = df[df["plan_status"] == "late"]
    bands = late.assign(band=late["plan_days_late"].map(_band)).groupby("band")["units"].sum()
    base_late = df[df["baseline_status"] == "late"]
    base_bands = base_late.assign(band=base_late["baseline_days_late"].map(_band)).groupby("band")["units"].sum()

    extra = df.loc[df["plan_status"] != "on time", "units"].sum() - df.loc[df["baseline_status"] == "late", "units"].sum()
    by_market = by("market")
    concentration = (max(r["extra_late_or_unbought_units"] for r in by_market) / extra * 100) if extra > 0 else 0.0
    # How much of the baseline's on-time delivery is physically possible: units it schedules above 100% capacity
    from engine.capacity import CapacityLedger
    prs = planner.prs.loc[df["pr_id"]]
    po = prs["run_id"].map(planner.runs.set_index("run_id")["po_execution_date"]).map(pd.Timestamp)
    ledger = CapacityLedger(planner.factories["weekly_capacity_units"].to_dict(),
                            planner.cfg["capacity"]["spread_over_manufacturing"])
    for r, start in zip(prs.itertuples(), po):
        ledger.add(r.assigned_factory, start, r.manufacturing_lead_time, r.requested_qty)
    t = ledger.table()
    above = float((t["units"] - t["weekly_capacity"]).clip(lower=0).sum()) if len(t) else 0.0
    weeks = int(t["week"].nunique()) if len(t) else 1
    valued = df[df["nsv"] > 0]
    return {
        "price_per_unit_usd": price, "price_range_usd": [19.0, 22.0],
        "order_value_per_unit_usd": float(valued["nsv"].sum() / valued["units"].sum()) if len(valued) else 0.0,
        "baseline_units_above_capacity": above,
        "baseline_units_above_capacity_pct": above / total * 100 if total else 0.0,
        "baseline_weeks_over_capacity": int((t["utilization_pct"] > 100).sum()) if len(t) else 0,
        "baseline_peak_utilization_pct": float(t["utilization_pct"].max()) if len(t) else 0.0,
        "firm_units_per_week": total / weeks,
        "network_weekly_capacity": float(planner.factories["weekly_capacity_units"].sum()),
        "firm_requisitions": int(len(df)), "firm_units": total,
        "plan": summary("plan_status"), "baseline": summary("baseline_status"),
        "plan_median_days_late": float(late["plan_days_late"].median()) if len(late) else 0.0,
        "extra_units_not_on_time": float(extra),
        "extra_usd_at_price": float(extra) * price,
        "extra_usd_range": [float(extra) * 19.0, float(extra) * 22.0],
        "largest_market_share_of_extra_pct": concentration,
        "late_bands": [{"band": b, "plan_units": float(bands.get(b, 0)), "baseline_units": float(base_bands.get(b, 0))}
                       for _, _, b in LATE_BANDS],
        "by_market": by_market, "by_category": by("category"), "by_product_line": by("product_line"),
        "by_channel": by("channel"), "by_segment": by("segment"), "top_customers": by("customer", top=15),
    }
