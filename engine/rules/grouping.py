"""Rule 2: 15-day temporal grouping (same article and same market only)."""
import pandas as pd


def group_by_rdd(rdds: list, window_days: int, mode: str = "anchor") -> list[list[int]]:
    """Split positions of a list of RDDs into lots.

    anchor: every RDD in a lot is within `window_days` of the lot's earliest RDD.
    chain:  consecutive RDDs are within `window_days` of each other.
    Returns lists of positions into `rdds`, each lot sorted by RDD.
    """
    order = sorted(range(len(rdds)), key=lambda i: pd.Timestamp(rdds[i]))
    lots: list[list[int]] = []
    for i in order:
        d = pd.Timestamp(rdds[i])
        if lots:
            ref = pd.Timestamp(rdds[lots[-1][0]] if mode == "anchor" else rdds[lots[-1][-1]])
            if (d - ref).days <= window_days:
                lots[-1].append(i)
                continue
        lots.append([i])
    return lots
