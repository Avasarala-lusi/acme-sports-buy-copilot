"""Buying windows and production weeks.

Client decision: one buying window per month, in the third week. The window date of a month is
the PO execution weekday that falls in that week (days 15-21 for the third week). Only the run whose
PO date is a window date commits purchases; the other weekly runs show a draft of the next window.
"""
from dataclasses import dataclass
from datetime import date, timedelta

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

    @classmethod
    def from_config(cls, cfg: dict) -> "BuyingCalendar":
        bw = cfg["buying_window"]
        return cls(bw["week_of_month"], bw["po_weekday"])

    def window_in_month(self, year: int, month: int) -> date:
        first = date(year, month, 7 * (self.week_of_month - 1) + 1)
        return first + timedelta(days=(self.po_weekday - first.weekday()) % 7)

    def on_or_after(self, d) -> date:
        """The first buying window on or after d."""
        d = _as_date(d)
        w = self.window_in_month(d.year, d.month)
        if w >= d:
            return w
        n = _add_months(d.replace(day=1), 1)
        return self.window_in_month(n.year, n.month)

    def after(self, d) -> date:
        """The first buying window strictly after d."""
        return self.on_or_after(_as_date(d) + timedelta(days=1))

    def on_or_before(self, d) -> date:
        """The latest buying window on or before d."""
        d = _as_date(d)
        w = self.window_in_month(d.year, d.month)
        if w <= d:
            return w
        p = _add_months(d.replace(day=1), -1)
        return self.window_in_month(p.year, p.month)

    def is_window(self, d) -> bool:
        d = _as_date(d)
        return self.window_in_month(d.year, d.month) == d

    def windows_from(self, d, n: int) -> list[date]:
        """The window on or after d and the n windows that follow it."""
        out = [self.on_or_after(d)]
        for _ in range(n):
            out.append(self.after(out[-1]))
        return out


def window_label(d) -> str:
    return f"WIN-{_as_date(d):%Y-%m}"


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
