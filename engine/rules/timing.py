"""Rule 1: purchase window."""
import pandas as pd

from engine.calendar import next_window_cutoff, window_label


def release_date(rdd, mfg_days: int, transit_days: int) -> pd.Timestamp:
    """PR release date = RDD - manufacturing lead time - transport lead time."""
    return pd.Timestamp(rdd) - pd.Timedelta(days=int(mfg_days) + int(transit_days))


def is_due(release, run_date, cutoff_day: int) -> bool:
    """Buy now when the release date falls before the next buying window."""
    return pd.Timestamp(release).date() < next_window_cutoff(run_date, cutoff_day)


def due_reason(release, run_date, cutoff_day: int) -> str:
    nxt = next_window_cutoff(run_date, cutoff_day)
    return (f"Rule 1: release {pd.Timestamp(release):%Y-%m-%d} is before the next buying "
            f"window ({window_label(nxt)}), so buy now")


def wait_reason(release, run_date, cutoff_day: int) -> str:
    nxt = next_window_cutoff(run_date, cutoff_day)
    return (f"Rule 1: release {pd.Timestamp(release):%Y-%m-%d} is on or after the next "
            f"buying window ({window_label(nxt)}), so wait")
