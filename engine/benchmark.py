"""Planner benchmark and the cost/service frontier, computed once per data and configuration and cached.

Approaches compared on the same requisitions (the firm demand the rule engine bought or sent to review):
- today's assignments (as in the data; capacity ignored),
- the rule engine,
- the network optimiser at each cost/service weight.

To keep the comparison honest, the optimiser's recommended weight is chosen on the tuning seasons only (raise the
service weight while each extra on-time unit costs less than the average cost of making a unit), and the results are
reported on the other seasons, which played no part in the choice.
"""
from __future__ import annotations

import json

import pandas as pd

from engine.optimizer import Network, by_factory, changes, evaluate, evaluate_as_is
from engine.planner import Planner


def _seasons(planner: Planner) -> list[str]:
    return list(dict.fromkeys(planner.runs["season"]))


def network_results(planner: Planner) -> dict:
    n = Network(planner)
    cfg = planner.cfg.get("benchmark", {})
    weights = [float(w) for w in cfg.get("weights", [0.0, 0.25, 0.5, 0.75, 1.0])]
    seasons = _seasons(planner)
    masks = {"all": None, **{s: n.u["season"] == s for s in seasons}}

    def per_season(fn):
        return {k: fn(m) for k, m in masks.items()}

    approaches = [
        {"key": "as_is", "label": "Today's assignments", "kind": "baseline",
         "results": per_season(lambda m: evaluate_as_is(planner, n.u, n.model, m))},
        {"key": "rules", "label": "Rule engine", "kind": "rules",
         "results": per_season(lambda m: evaluate(planner, n.u, n.opts, n.rule, m))},
    ]
    plans = []
    for w in weights:
        s = n.solve(w)
        approaches.append({"key": f"opt_{w:g}", "label": f"Optimiser, weight {w:g}", "kind": "optimiser", "weight": w,
                           "status": s["status"], "gap_pct": s["gap_pct"], "seconds": s["seconds"],
                           "results": per_season(lambda m, c=s["choice"]: evaluate(planner, n.u, n.opts, c, m))})
        plans.append({"weight": w, "by_factory": by_factory(n.u, n.opts, s["choice"]),
                      "changes": changes(n.u, n.opts, n.rule, s["choice"])})

    tuning = [s for s in cfg.get("tuning_seasons", seasons[:2]) if s in seasons]
    test = [s for s in cfg.get("test_seasons", seasons[2:]) if s in seasons]

    # Raise the service weight while each extra on-time unit (tuning seasons) costs less than making a unit.
    candidates = sorted((a for a in approaches if a["kind"] == "optimiser"), key=lambda a: a["weight"])

    def totals(a):
        r = [a["results"][k] for k in tuning]
        return sum(x["on_time_units"] for x in r), sum(x["production_cost_usd"] for x in r), sum(x["units_bought"] for x in r)

    chosen, steps = candidates[0], []
    for a in candidates[1:]:
        (u0, c0, b0), (u1, c1, b1) = totals(chosen), totals(a)
        unit_cost = c0 / b0 if b0 else 0.0
        per_unit = (c1 - c0) / (u1 - u0) if u1 > u0 else float("inf")
        steps.append({"from": chosen["weight"], "to": a["weight"], "extra_on_time_units": u1 - u0,
                      "extra_cost_usd": c1 - c0, "cost_per_extra_on_time_unit_usd": per_unit,
                      "average_unit_cost_usd": unit_cost, "accepted": per_unit <= unit_cost})
        if per_unit > unit_cost:
            break
        chosen = a
    return {
        "seasons": seasons, "tuning_seasons": tuning, "test_seasons": test, "weights": weights,
        "selected_weight": chosen["weight"],
        "selection_rule": "raise the service weight while each extra on-time unit on the tuning seasons costs less than "
                          "the average cost of making a unit",
        "selection_steps": steps,
        "approaches": approaches, "plans": plans,
        "universe": {"lots": int(len(n.u)), "requisitions": int(n.u["pr_ids"].str.count(",").sum() + len(n.u)),
                     "units": float(n.u["qty"].sum()),
                     "from_review_lots": int(n.u["rule_factory"].isna().sum())},
    }


def cached_network_results(planner: Planner) -> dict:
    """A few minutes the first time (one solve per weight); cached next to the planned engine (same key)."""
    from engine.config import ROOT
    from engine.output import _config_hash

    path = ROOT / planner.cfg["data"]["output_dir"] / f"network_{_config_hash(planner.cfg)}.json"
    if path.exists():
        return json.loads(path.read_text())
    out = json.loads(json.dumps(network_results(planner), default=lambda x: None if pd.isna(x) else str(x)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return out
