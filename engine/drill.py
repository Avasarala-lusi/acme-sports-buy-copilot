"""Disruption drill: close one factory for a period and compare how the rule engine and the optimiser respond.

The closure is known from the start of planning (a drill, not a forecast). The rule engine re-plans every window
with the factory's capacity removed in those weeks, so lots move down the backup chain or go to planner review.
The optimiser re-plans the same lots with those factory-weeks at zero capacity. Both are compared with their
undisrupted plans on the same KPIs.
"""
from __future__ import annotations

import copy

import pandas as pd

from engine.optimizer import Network, by_factory, evaluate
from engine.planner import Planner


def run_drill(base: Planner, factory: str, start, end, weight: float, base_network: Network | None = None) -> dict:
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    if factory not in base.factories.index:
        raise ValueError(f"unknown factory {factory}")
    if end < start:
        raise ValueError("the closure ends before it starts")
    closures = [(factory, start, end)]
    cfg = copy.deepcopy(base.cfg)
    cfg["disruption"] = {"closures": closures}
    hit = Planner(data=base.data, config=cfg)
    hit.plan_all()

    n = base_network or Network(base)
    hit_n = Network(hit)
    opt = n.solve(weight)
    opt_hit = n.solve(weight, closures=closures)
    plans = {
        "rules": evaluate(base, n.u, n.opts, n.rule, closures=closures),
        "rules_disrupted": evaluate(hit, hit_n.u, hit_n.opts, hit_n.rule, closures=closures),
        "optimiser": evaluate(base, n.u, n.opts, opt["choice"], closures=closures),
        "optimiser_disrupted": evaluate(base, n.u, n.opts, opt_hit["choice"], closures=closures),
    }
    # lots of the normal rule plan whose production at the factory overlaps the closure
    hit_lots = [i for i, j in n.rule.items() if j >= 0 and n.opts.loc[j, "factory"] == factory
                and any(n.opts.loc[j, "alloc"][k][1] > 0 and start <= pd.Timestamp(w) <= end
                        for k, (w, _) in enumerate(n.opts.loc[j, "alloc"]))]
    return {
        "factory": factory, "start": start.date().isoformat(), "end": end.date().isoformat(), "weight": weight,
        "weeks_closed": int(((end - start).days // 7) + 1),
        "affected_lots": len(hit_lots), "affected_units": float(n.u.loc[hit_lots, "qty"].sum()),
        "plans": plans,
        "by_factory": {"rules": by_factory(n.u, n.opts, n.rule),
                       "rules_disrupted": by_factory(hit_n.u, hit_n.opts, hit_n.rule),
                       "optimiser": by_factory(n.u, n.opts, opt["choice"]),
                       "optimiser_disrupted": by_factory(n.u, n.opts, opt_hit["choice"])},
    }
