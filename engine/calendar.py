"""Buying windows and production weeks.

MID/EOM mapping is configurable and provisional. Formal purchases require a matching
run-log PO date; other weekly runs preview the next window. The earlier once-monthly
calendar remains an explicit compatibility option, not the default.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from calendar import monthrange
from functools import lru_cache

import pandas as pd


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    return date(d.year + m // 12, m % 12 + 1, d.day)


def _as_date(d) -> date:
    return pd.Timestamp(d).date()


@dataclass(frozen=True)
class BuyingCalendar:
    week_of_month: int = 3
    po_weekday: int = 2
    frequency: str = "semi_monthly"
    mid_cutoff_day: int = 15

    @classmethod
    def from_config(cls, cfg: dict) -> "BuyingCalendar":
        bw = cfg["buying_window"]
        return cls(bw.get("week_of_month", 3), bw["po_weekday"],
                   bw.get("frequency", "semi_monthly"), bw.get("mid_cutoff_day", 15))

    def dates_in_month(self, year: int, month: int) -> list[date]:
        if self.frequency == "monthly":
            return [self.window_in_month(year, month)]
        # Configurable assumption pending client confirmation: last PO weekday on/before
        # MID cutoff, and last PO weekday of the month. No calendar date is a purchase
        # unless a matching run is present (Planner.window_run).
        dates = [date(year, month, self.mid_cutoff_day), date(year, month, monthrange(year, month)[1])]
        return [d - timedelta(days=(d.weekday() - self.po_weekday) % 7) for d in dates]

    def window_in_month(self, year: int, month: int) -> date:
        first = date(year, month, 7 * (self.week_of_month - 1) + 1)
        return first + timedelta(days=(self.po_weekday - first.weekday()) % 7)

    def on_or_after(self, d) -> date:
        """The first buying window on or after d."""
        d = _as_date(d)
        for w in self.dates_in_month(d.year, d.month):
            if w >= d:
                return w
        n = _add_months(d.replace(day=1), 1)
        return self.dates_in_month(n.year, n.month)[0]

    def after(self, d) -> date:
        """The first buying window strictly after d."""
        return self.on_or_after(_as_date(d) + timedelta(days=1))

    def on_or_before(self, d) -> date:
        """The latest buying window on or before d."""
        d = _as_date(d)
        for w in reversed(self.dates_in_month(d.year, d.month)):
            if w <= d:
                return w
        p = _add_months(d.replace(day=1), -1)
        return self.dates_in_month(p.year, p.month)[-1]

    def is_window(self, d) -> bool:
        d = _as_date(d)
        return d in self.dates_in_month(d.year, d.month)

    def windows_from(self, d, n: int) -> list[date]:
        """The window on or after d and the n windows that follow it."""
        out = [self.on_or_after(d)]
        for _ in range(n):
            out.append(self.after(out[-1]))
        return out


def window_label(d) -> str:
    d = _as_date(d)
    return f"WIN-{d:%Y-%m}-{'MID' if d.day <= 15 else 'EOM'}"


@lru_cache(maxsize=8192)
def manufacturing_weights(start, days: float) -> tuple:
    """Calendar-day duration, [start, completion), Mon–Fri capacity only.

    Fractional midpoint lead times retain their partial-day weight. No holiday
    calendar is assumed. A positive production period with no workdays is invalid.
    """
    start = pd.Timestamp(start)
    if days <= 0:
        raise ValueError("Manufacturing lead time must be positive")
    end = start + pd.Timedelta(days=days)
    counts = {}
    day = start.normalize()
    while day < end:
        if day.weekday() < 5:
            weight = (min(day + pd.Timedelta(days=1), end) - max(day, start)).total_seconds() / 86400
            if weight > 0:
                w = week_start(day)
                counts[w] = counts.get(w, 0.0) + weight
        day += pd.Timedelta(days=1)
    total = sum(counts.values())
    if total <= 0:
        raise ValueError("Production interval contains no business days")
    return tuple((w, n / total) for w, n in sorted(counts.items()))


def week_start(d) -> date:
    d = _as_date(d)
    return d - timedelta(days=d.weekday())


def production_weeks(start, days: int) -> list[date]:
    """Monday-dated weeks covered by a production run of `days` days starting at `start`."""
    first = week_start(start)
    last = week_start(pd.Timestamp(start) + pd.Timedelta(days=max(days, 1) - 1))
    n = (last - first).days // 7 + 1
    return [first + timedelta(weeks=i) for i in range(n)]


def weeks_between(lo, hi) -> list[date]:
    """Monday-dated weeks from the week containing lo up to, not including, the week containing hi."""
    first, last = week_start(lo), week_start(hi)
    return [first + timedelta(weeks=i) for i in range((last - first).days // 7)]
