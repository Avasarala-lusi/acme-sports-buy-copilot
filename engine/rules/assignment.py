"""Factory certification and capacity routing (spec section 3)."""
from dataclasses import dataclass, field


@dataclass
class Assignment:
    factory: str
    routed_to_backup: bool = False
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def choose_factory(primary: str, backup: str, certified: set[str],
                   util_primary: float, util_backup: float | None,
                   threshold_pct: float, both_full_policy: str) -> Assignment:
    """Pick the factory for a lot.

    util_* are the current utilisation (%) of each factory over the lot's production weeks,
    before adding the lot. The spec routes to the backup once the primary is >= threshold.
    """
    if primary not in certified:
        raise ValueError(f"primary factory {primary} is not certified for this article")

    if util_primary < threshold_pct:
        return Assignment(primary, reasons=[
            f"Capacity: primary {primary} at {util_primary:.0f}% (< {threshold_pct:.0f}%), kept on primary"])

    if backup not in certified:
        return Assignment(primary, warnings=[
            f"Capacity: primary {primary} at {util_primary:.0f}% but backup {backup} is not certified; "
            "kept on primary, planner review needed"])

    if util_backup < threshold_pct:
        return Assignment(backup, routed_to_backup=True, reasons=[
            f"Capacity: primary {primary} at {util_primary:.0f}% (>= {threshold_pct:.0f}%), "
            f"routed to backup {backup} at {util_backup:.0f}%"])

    if both_full_policy != "least_loaded_with_warning":
        raise ValueError(f"unknown policy {both_full_policy}")
    target = backup if util_backup < util_primary else primary
    return Assignment(target, routed_to_backup=target == backup, warnings=[
        f"Capacity conflict: primary {primary} at {util_primary:.0f}% and backup {backup} at "
        f"{util_backup:.0f}% are both >= {threshold_pct:.0f}%; assigned to the less loaded "
        f"({target}), planner review needed"])
