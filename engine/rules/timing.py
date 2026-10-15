"""Rule 1: purchase window."""
import pandas as pd

from engine.calendar import window_label


def release_date(rdd, mfg_days: int, transit_days: int) -> pd.Timestamp:
    """PR release date = RDD - manufacturing lead time - transport lead time."""
    return pd.Timestamp(rdd) - pd.Timedelta(days=int(mfg_days) + int(transit_days))


def is_due(release, next_window) -> bool:
    """Buy in this window when waiting for the next one would start production too late."""
    return pd.Timestamp(release).date() < pd.Timestamp(next_window).date()


def due_reason(release, window, next_window) -> str:
    return (f"Rule 1: release {pd.Timestamp(release):%Y-%m-%d} is before the next buying window "
            f"({window_label(next_window)}), so buy in {window_label(window)}")


def wait_reason(release, next_window) -> str:
    return (f"Rule 1: release {pd.Timestamp(release):%Y-%m-%d} is on or after the next buying "
            f"window ({window_label(next_window)}), so wait")
