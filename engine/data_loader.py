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
        issues.append(f"utilization: {over} of {len(data.utilization)} factory-weeks above 100% capacity "
                      f"(max {data.utilization['utilization_pct'].max():,.0f}%); under client review, "
                      "the planner uses its own rolling ledger instead")

    so, customers = data.sales_orders, data.customers
    known = set(customers["customer_id"])
    if "customer_id" in prs:
        unknown = ~prs["customer_id"].isin(known)
        if unknown.any():
            issues.append(f"prs: {unknown.sum():,} rows reference unknown customers")
        both = so.merge(prs[["pr_id", "customer_id"]], on="pr_id", suffixes=("", "_pr"))
        mismatch = (both["customer_id"] != both["customer_id_pr"]).sum()
        if mismatch:
            issues.append(f"sales_orders: {mismatch:,} orders name a different customer than their requisition")
    unknown = ~so["customer_id"].isin(known)
    if unknown.any():
        issues.append(f"sales_orders: {unknown.sum():,} orders have no customer record")

    c_rated = customers.loc[customers["credit_rating"] == "C", "customer_id"]
    if len(c_rated) and not so["customer_id"].isin(c_rated).any():
        issues.append(f"customers: the {len(c_rated)} C-rated customers have no sales orders, "
                      "so C-rated exposure is $0")

    issues += _backup_findings(data)

    # a customer may serve several markets (data v5 'markets', e.g. MX|US)
    served = customers.set_index("customer_id")
    served = (served["markets"] if "markets" in served else served["market"]).astype(str).str.split("|")
    orders = so.merge(prs[["pr_id", "market_destination"]].rename(columns={"market_destination": "dest"}), on="pr_id")
    outside = [d not in served.get(c, [d]) for c, d in zip(orders["customer_id"], orders["dest"])]
    share = sum(outside) / len(orders) if len(orders) else 0
    if share > 0:
        issues.append(f"sales_orders: for {share:.0%} of orders the destination is not a market the customer serves; "
                      "destination is used")

    return issues


def _backup_findings(data: AcmeData) -> list[str]:
    """Factory-level backup chain (loops, end point) and its agreement with article-level backups."""
    issues = []
    chain = data.factories.set_index("factory_id")["backup_factory"].dropna().to_dict()
    loops = set()
    for start in chain:
        seen, f = [], start
        while f in chain and f not in seen:
            seen.append(f)
            f = chain[f]
        if f in seen:
            loop = seen[seen.index(f):]
            loops.add(" → ".join(loop + [loop[0]]))
    if loops:
        issues.append("factories: factory-level backups form a loop (" + "; ".join(sorted(loops)) + ")")
    ends = sorted(set(data.factories["factory_id"]) - set(chain))
    if ends and not loops:
        issues.append(f"factories: factory-level backup chain has no loops and ends at {', '.join(ends)} "
                      "(last resort, no backup of its own)")

    arts = data.articles.merge(
        data.factories[["factory_id", "backup_factory"]].rename(
            columns={"factory_id": "primary_factory", "backup_factory": "factory_level_backup"}),
        on="primary_factory")
    differ = (arts["backup_factory"] != arts["factory_level_backup"]).sum()
    if differ:
        issues.append(f"articles: article-level and factory-level backups differ for {differ} of "
                      f"{len(arts)} articles; which one is used is the backup_source setting (open question)")
    return issues
