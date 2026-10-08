"""Manual planner decisions (the Tuesday Go/No-Go), saved and applied on top of the automatic plan.

The spec requires the tool to distinguish automatically triggered rules from manually overridden
decisions. The engine's plan is never changed; overrides are stored separately and applied to
produce the "effective" plan that the app shows and exports.

Supported overrides per run:
  - lot decision: Buy (default) | No-Go | Delay
  - lot factory switch (must be certified)
  - customer hold (removes that customer's units from every lot in the run)
"""
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from engine.config import ROOT, load_config
from engine.planner import Planner

DECISIONS = ["Buy", "No-Go", "Delay"]


class OverrideStore:
    def __init__(self, path: Path | str | None = None):
        cfg = load_config()
        self.path = Path(path or ROOT / cfg["data"]["output_dir"] / "overrides.json")
        self.data: dict = json.loads(self.path.read_text()) if self.path.exists() else {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2))

    def run(self, run_id: str) -> dict:
        return self.data.setdefault(run_id, {"lots": {}, "held_customers": []})

    def set_lot(self, planner: Planner, run_id: str, lot_id: str, decision: str = "Buy",
                factory: str | None = None, note: str = "") -> None:
        if decision not in DECISIONS:
            raise ValueError(f"decision must be one of {DECISIONS}")
        lots = planner.run_result(run_id).lots.set_index("lot_id")
        if lot_id not in lots.index:
            raise KeyError(f"unknown lot {lot_id} in {run_id}")
        article = lots.loc[lot_id, "article_id"]
        if factory == lots.loc[lot_id, "assigned_factory"]:
            factory = None
        if factory and factory not in planner.certified[article]:
            raise ValueError(f"{factory} is not certified for {article}")
        if decision == "Buy" and not factory and not note:
            self.run(run_id)["lots"].pop(lot_id, None)
        else:
            self.run(run_id)["lots"][lot_id] = {"decision": decision, "factory": factory, "note": note,
                                                "updated_at": datetime.now().isoformat(timespec="seconds")}
        self.save()

    def hold_customer(self, run_id: str, customer_id: str) -> None:
        held = self.run(run_id)["held_customers"]
        if customer_id not in held:
            held.append(customer_id)
        self.save()

    def release_customer(self, run_id: str, customer_id: str) -> None:
        held = self.run(run_id)["held_customers"]
        if customer_id in held:
            held.remove(customer_id)
        self.save()

    def reset(self, run_id: str) -> None:
        self.data.pop(run_id, None)
        self.save()

    def count(self, run_id: str) -> int:
        r = self.data.get(run_id, {})
        return len(r.get("lots", {})) + len(r.get("held_customers", []))


def effective_lots(planner: Planner, run_id: str, store: OverrideStore) -> pd.DataFrame:
    """The run's lots with saved manual decisions applied. Untouched lots stay automatic."""
    lots = planner.run_result(run_id).lots.copy()
    lots["decision"] = "Buy"
    lots["override_note"] = ""
    overrides = store.data.get(run_id, {})
    held = set(overrides.get("held_customers", []))
    lot_ov = overrides.get("lots", {})
    if not held and not lot_ov:
        return lots

    moq = planner.cfg["quantities"]["moq_per_market"]
    po = pd.Timestamp(planner.runs.set_index("run_id").loc[run_id, "po_execution_date"])
    rows = []
    for lot in lots.to_dict("records"):
        ids = lot["pr_ids"].split(",")
        notes, changed = [], False

        keep = [p for p in ids if planner.rows[p]["customer_id"] not in held]
        if len(keep) < len(ids):
            removed = [p for p in ids if p not in keep]
            held_here = sorted({planner.rows[p]["customer_id"] for p in removed})
            notes.append(f"Customer hold ({', '.join(held_here)}): "
                         f"{sum(planner.rows[p]['requested_qty'] for p in removed):,.0f} units removed")
            changed = True

        ov = lot_ov.get(lot["lot_id"], {})
        factory = ov.get("factory") or lot["assigned_factory"]
        if ov.get("factory"):
            notes.append(f"Factory switched {lot['assigned_factory']} → {factory}")
            changed = True
        if ov.get("decision", "Buy") != "Buy":
            lot["decision"] = ov["decision"]
            changed = True
        if ov.get("note"):
            notes.append(ov["note"])
            changed = True

        if not keep:
            lot.update(decision="No-Go", consolidated_qty=0, n_prs=0, pr_ids="", total_cost_usd=0.0,
                       nsv_usd=0.0, on_time_units=0.0)
            notes.append("All units held")
        elif changed:
            qty = sum(planner.rows[p]["requested_qty"] for p in keep)
            rdd = min(planner.rows[p]["rdd_original"] for p in keep)
            m, t = planner.lot_lead_times(keep, factory)
            release = rdd - pd.Timedelta(days=m + t)
            start = max(release, po)
            arrival = start + pd.Timedelta(days=m + t)
            mult = float(planner.factories.loc[factory, "cost_multiplier"])
            lot.update(
                consolidated_qty=int(qty), n_prs=len(keep), pr_ids=",".join(keep), earliest_rdd=rdd,
                assigned_factory=factory, cost_multiplier=mult,
                total_cost_usd=qty * lot["unit_cost_usd"] * mult,
                nsv_usd=float(sum(planner.rows[p]["nsv"] for p in keep)),
                release_date=release, production_start=start, expected_arrival=arrival,
                on_time=arrival <= rdd, suggested_rdd=rdd if arrival <= rdd else arrival,
                on_time_units=float(sum(planner.rows[p]["requested_qty"] for p in keep
                                        if planner.rows[p]["rdd_original"] >= arrival)),
            )
            if qty < moq and lot["decision"] == "Buy":
                lot["warnings"] = " | ".join(x for x in [lot["warnings"], f"Below MOQ after override: {qty:,.0f} < {moq}"] if x)

        if changed or not keep:
            lot["decision_type"] = "manual"
            lot["override_note"] = "; ".join(notes)
        rows.append(lot)
    return pd.DataFrame(rows)


def effective_fact_table(planner: Planner, run_id: str, store: OverrideStore) -> pd.DataFrame:
    """fact_buy_plan_suggestions for one run, after manual decisions (Buy lots only)."""
    from engine.output import SPEC_COLUMNS
    lots = effective_lots(planner, run_id, store)
    lots = lots[(lots["decision"] == "Buy") & (lots["consolidated_qty"] > 0)].copy()
    lots["suggestion_id"] = "SUG-" + lots["lot_id"]
    lots["suggested_rdd"] = pd.to_datetime(lots["suggested_rdd"]).dt.date
    return lots[SPEC_COLUMNS].reset_index(drop=True)
