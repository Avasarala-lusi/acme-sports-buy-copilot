"""Buying windows and production weeks.

Client decision: one buying window per month, in the third week. A requisition is bought
"now" when waiting for the next window would start production too late.
"""
from datetime import date, timedelta

import pandas as pd


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    return date(d.year + m // 12, m % 12 + 1, d.day)


def window_cutoff(d, cutoff_day: int) -> date:
    """The buying window that is open at date d (the next cutoff on or after d)."""
    d = pd.Timestamp(d).date()
    cutoff = date(d.year, d.month, cutoff_day)
    return cutoff if d <= cutoff else _add_months(cutoff, 1)


def next_window_cutoff(d, cutoff_day: int) -> date:
    return _add_months(window_cutoff(d, cutoff_day), 1)


def natural_window(release, cutoff_day: int) -> date:
    """The window in which demand with this release date would normally be bought."""
    r = pd.Timestamp(release).date()
    cutoff = date(r.year, r.month, cutoff_day)
    return cutoff if r >= cutoff else _add_months(cutoff, -1)


def window_label(d: date) -> str:
    return f"WIN-{d:%Y-%m}"


def week_start(d) -> date:
    d = pd.Timestamp(d).date()
    return d - timedelta(days=d.weekday())


def production_weeks(start, days: int) -> list[date]:
    """Monday-dated weeks covered by a production run of `days` days starting at `start`."""
    first = week_start(start)
    last = week_start(pd.Timestamp(start) + pd.Timedelta(days=max(days, 1) - 1))
    n = (last - first).days // 7 + 1
    return [first + timedelta(weeks=i) for i in range(n)]
