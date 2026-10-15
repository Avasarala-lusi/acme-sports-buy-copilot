"""Rolling capacity ledger built from our own assignments (client decision).

Units are recorded per factory per production week. The static fact_factory_utilization
table is not used for planning decisions.
"""
from collections import defaultdict
from copy import deepcopy
from datetime import date

from engine.calendar import production_weeks


def _weekly_units():
    return defaultdict(float)


class CapacityLedger:
    def __init__(self, weekly_capacity: dict[str, int], spread: bool = True):
        self.capacity = dict(weekly_capacity)
        self.spread = spread
        self.units: dict[str, dict[date, float]] = defaultdict(_weekly_units)

    def copy(self) -> "CapacityLedger":
        new = CapacityLedger(self.capacity, self.spread)
        new.units = deepcopy(self.units)
        return new

    def weeks_for(self, start, mfg_days: int) -> list[date]:
        weeks = production_weeks(start, mfg_days)
        return weeks if self.spread else weeks[:1]

    def utilization(self, factory: str, weeks: list[date]) -> float:
        """Highest utilisation (%) across the given weeks."""
        cap = self.capacity[factory]
        return max(self.units[factory][w] / cap * 100 for w in weeks)

    def utilization_with(self, factory: str, start, mfg_days: int, qty: float) -> float:
        """Highest utilisation (%) over the lot's production weeks if the lot were added."""
        weeks = self.weeks_for(start, mfg_days)
        per_week = qty / len(weeks)
        cap = self.capacity[factory]
        return max((self.units[factory][w] + per_week) / cap * 100 for w in weeks)

    def add(self, factory: str, start, mfg_days: int, qty: float) -> None:
        weeks = self.weeks_for(start, mfg_days)
        per_week = qty / len(weeks)
        for w in weeks:
            self.units[factory][w] += per_week

    def remove(self, factory: str, start, mfg_days: int, qty: float) -> None:
        self.add(factory, start, mfg_days, -qty)

    def table(self):
        import pandas as pd
        rows = [
            {"factory_id": f, "week": w, "units": u,
             "weekly_capacity": self.capacity[f], "utilization_pct": u / self.capacity[f] * 100}
            for f, weeks in self.units.items() for w, u in weeks.items() if abs(u) > 1e-9
        ]
        cols = ["factory_id", "week", "units", "weekly_capacity", "utilization_pct"]
        return pd.DataFrame(rows, columns=cols).sort_values(["factory_id", "week"]).reset_index(drop=True)
