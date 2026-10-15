"""Write the deliverable tables, and cache a fully planned engine on disk."""
import hashlib
import json
import pickle
from pathlib import Path

import pandas as pd

from engine.accounting import accounting_report, rule_violations
from engine.config import ROOT, load_config
from engine.metrics import comparison_table
from engine.planner import Planner

SPEC_COLUMNS = ["suggestion_id", "run_id", "article_id", "market_destination", "consolidated_qty",
                "suggested_rdd", "assigned_factory", "is_piggyback_applied", "piggyback_source_window"]


def fact_buy_plan_suggestions(planner: Planner, run_ids: list[str] | None = None) -> pd.DataFrame:
    """The spec's output table (Table 9): committed purchases only."""
    lots = planner.bought_lots()
    if run_ids is not None:
        lots = lots[lots["run_id"].isin(run_ids)]
    out = lots.copy()
    out["suggestion_id"] = "SUG-" + out["lot_id"]
    out["suggested_rdd"] = pd.to_datetime(out["suggested_rdd"]).dt.date
    return out[SPEC_COLUMNS].reset_index(drop=True)


def write_outputs(planner: Planner, out_dir: Path | None = None) -> Path:
    out_dir = Path(out_dir or ROOT / planner.cfg["data"]["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    fact_buy_plan_suggestions(planner).to_csv(out_dir / "fact_buy_plan_suggestions.csv", index=False)
    planner.all_lots().to_csv(out_dir / "buy_plan_lot_details.csv", index=False)
    planner.pr_outcomes().to_csv(out_dir / "pr_outcomes.csv", index=False)
    planner.ledger.table().to_csv(out_dir / "capacity_ledger.csv", index=False)
    comparison_table(planner).to_csv(out_dir / "comparison_vs_as_is.csv", index=False)
    report = accounting_report(planner)
    report["rule_violations"] = len(rule_violations(planner))
    (out_dir / "accounting_report.json").write_text(json.dumps(report, indent=2, default=str))
    return out_dir


def _config_hash(cfg: dict) -> str:
    """Changes when the config, any engine source file or any input data file changes, so stale caches are never used."""
    h = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode())
    for src in sorted((ROOT / "engine").rglob("*.py")):
        h.update(src.read_bytes())
    for data_file in sorted((ROOT / cfg["data"]["raw_dir"]).glob("*.csv")):
        st = data_file.stat()
        h.update(f"{data_file.name}:{st.st_size}:{st.st_mtime_ns}".encode())
    return h.hexdigest()[:12]


def get_planner(plan_all: bool = True, cache_dir: Path | None = None) -> Planner:
    """Load a planned engine from disk, or plan from scratch and cache it."""
    cfg = load_config()
    cache = Path(cache_dir or ROOT / cfg["data"]["output_dir"]) / f"planner_{_config_hash(cfg)}.pkl"
    if cache.exists():
        with open(cache, "rb") as f:
            return pickle.load(f)
    planner = Planner(config=cfg)
    if plan_all:
        planner.plan_all()
        cache.parent.mkdir(parents=True, exist_ok=True)
        with open(cache, "wb") as f:
            pickle.dump(planner, f)
    return planner
