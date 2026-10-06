"""Load and validate the nine ACME CSV tables.

Validation reports problems instead of raising, so the app can show a data-health panel.
"""
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from engine.config import ROOT, load_config

TABLES = {
    "factories": "dim_factory_master.csv",
    "cert_matrix": "dim_factory_article_matrix.csv",
    "articles": "dim_article_master.csv",
    "customers": "dim_customer_master.csv",
    "runs": "fact_mrp_run_log.csv",
    "prs": "fact_purchase_requisitions.csv",
    "utilization": "fact_factory_utilization.csv",
    "sales_orders": "fact_sales_orders.csv",
    "buy_plan": "fact_buy_plan_suggestions.csv",
}

PRIMARY_KEYS = {
    "factories": ["factory_id"],
    "cert_matrix": ["article_id", "factory_id"],
    "articles": ["article_id"],
    "customers": ["customer_id"],
    "runs": ["run_id"],
    "prs": ["pr_id"],
    "sales_orders": ["order_id"],
}

DATE_COLUMNS = {
    "prs": ["rdd_original", "mrp_run_date"],
    "runs": ["as_is_plan_date", "go_nogo_date", "po_execution_date",
             "factory_transmission_date", "factory_confirm_deadline"],
    "utilization": ["mrp_run_date"],
}


@dataclass
class AcmeData:
    tables: dict[str, pd.DataFrame]
    issues: list[str] = field(default_factory=list)

    def __getattr__(self, name: str) -> pd.DataFrame:
        tables = self.__dict__.get("tables")
        if tables is None or name not in tables:
            raise AttributeError(name)
        return tables[name]


def load_data(raw_dir: Path | str | None = None) -> AcmeData:
    cfg = load_config()
    raw = Path(raw_dir) if raw_dir else ROOT / cfg["data"]["raw_dir"]
    tables = {}
    for name, filename in TABLES.items():
        df = pd.read_csv(raw / filename)
        for col in DATE_COLUMNS.get(name, []):
            df[col] = pd.to_datetime(df[col])
        tables[name] = df

    # channel_id is stored as 1/2 in the CSV; the spec calls it CHAR(2) "01"/"02".
    tables["prs"]["channel_id"] = tables["prs"]["channel_id"].astype(int).map("{:02d}".format)

    data = AcmeData(tables)
    data.issues = validate(data)
    return data


def validate(data: AcmeData) -> list[str]:
    issues = []
    for name, keys in PRIMARY_KEYS.items():
        dupes = data.tables[name].duplicated(keys).sum()
        if dupes:
            issues.append(f"{name}: {dupes} duplicate keys on {keys}")

    prs, articles = data.prs, data.articles
    missing = ~prs["article_id"].isin(articles["article_id"])
    if missing.any():
        issues.append(f"prs: {missing.sum()} rows reference unknown articles")

    certified = data.cert_matrix.loc[data.cert_matrix["is_certified"], ["article_id", "factory_id"]]
    pairs = prs[["article_id", "assigned_factory"]].rename(columns={"assigned_factory": "factory_id"})
    uncertified = ~pairs.merge(certified, how="left", indicator=True)["_merge"].eq("both")
    if uncertified.any():
        issues.append(f"prs: {uncertified.sum()} rows assigned to uncertified factories")

    not_future = (prs["rdd_original"] <= prs["mrp_run_date"]).sum()
    if not_future:
        issues.append(f"prs: {not_future} rows have RDD on or before the MRP run date")

    over = (data.utilization["utilization_pct"] > 100).sum()
    if over:
        issues.append(f"utilization: {over} factory-weeks above 100% capacity (under client review)")

    return issues
