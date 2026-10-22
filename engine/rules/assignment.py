"""Factory certification and capacity routing (spec section 3).

Loads are projected: each factory's utilisation over the lot's production weeks *including the lot*.
A lot stays on its primary while the projected load is below the threshold, otherwise it goes to a
certified backup below the threshold. If neither is below the threshold, the less-loaded option is used
only while it stays within the hard limit; beyond that the lot is either sent for planner review or,
for every article including last-chance, retained for planner review. No policy waives the hard ceiling.
"""
from dataclasses import dataclass, field

OK = "ok"                         # below the threshold
ABOVE_THRESHOLD = "above_threshold"  # at or above the threshold but within the hard limit
OVER_LAST_CHANCE = "over_capacity_last_chance"
OVER_CAPACITY = "over_capacity"   # only with when_no_capacity: buy_with_warning
REVIEW = "review"                 # not bought: needs a planner decision

STATUS_LABELS = {
    OK: "Within capacity",
    ABOVE_THRESHOLD: "Above threshold, within capacity",
    OVER_LAST_CHANCE: "Over capacity (last chance)",
    OVER_CAPACITY: "Over capacity",
    REVIEW: "Needs planner review",
}
POLICIES = ("planner_review", "buy_with_warning")


@dataclass
class Assignment:
    factory: str
    routed_to_backup: bool = False
    status: str = OK
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def choose_factory(primary: str, backup: str, certified: set[str],
                   load_primary: float, load_backup: float | None,
                   threshold_pct: float, hard_limit_pct: float = 100.0,
                   last_chance: bool = False, no_capacity_policy: str = "planner_review") -> Assignment:
    """Pick the factory for a lot with a single backup (see choose_from_chain).

    load_* are each factory's highest weekly utilisation (%) over the lot's production weeks with the lot
    added. load_backup is None when the backup is not certified for the article.
    """
    loads = {primary: load_primary}
    if backup in certified and load_backup is not None:
        loads[backup] = load_backup
    return choose_from_chain(primary, [backup], certified, loads, threshold_pct, hard_limit_pct,
                             last_chance, no_capacity_policy)


def choose_from_chain(primary: str, chain: list[str], certified: set[str], loads: dict[str, float],
                      threshold_pct: float, hard_limit_pct: float = 100.0,
                      last_chance: bool = False, no_capacity_policy: str = "planner_review") -> Assignment:
    """Pick the factory for a lot: the primary, else the first backup in the chain below the threshold.

    `chain` is the ordered backups (one for article-level backups; for the factory-level chain, the primary's
    backup, its backup, and so on to the last resort). Uncertified backups are skipped. `loads` holds each
    certified option's highest weekly utilisation (%) over the lot's production weeks with the lot added.
    """
    if primary not in certified:
        raise ValueError(f"primary factory {primary} is not certified for this article")
    if no_capacity_policy not in POLICIES:
        raise ValueError(f"unknown policy {no_capacity_policy}")

    load_primary = loads[primary]
    if load_primary < threshold_pct:
        return Assignment(primary, reasons=[
            f"Capacity: primary {primary} at {load_primary:.0f}% with this lot (< {threshold_pct:.0f}%), kept on primary"])

    usable = [f for f in chain if f in certified and f in loads and f != primary]
    skipped = [f for f in chain if f not in certified]
    for n, f in enumerate(usable, 1):
        if loads[f] < threshold_pct:
            step = "backup" if n == 1 else f"backup no. {n} in the chain"
            return Assignment(f, routed_to_backup=True, reasons=[
                f"Capacity: primary {primary} would reach {load_primary:.0f}% with this lot (>= {threshold_pct:.0f}%), "
                + "".join(f"{g} {loads[g]:.0f}%, " for g in usable[:n - 1])
                + f"routed to {step} {f} at {loads[f]:.0f}%"])

    options = {primary: load_primary, **{f: loads[f] for f in usable}}
    target = min(options, key=options.get)
    load = options[target]
    text = ", ".join(f"{f} {u:.1f}%" for f, u in options.items())
    if skipped:
        text += f" ({', '.join(skipped)} not certified)"
    a = Assignment(target, routed_to_backup=target != primary)

    if load <= hard_limit_pct:
        a.status = ABOVE_THRESHOLD
        a.warnings.append(f"Capacity: no certified option below {threshold_pct:.0f}% with this lot ({text}); "
                          f"assigned to {target}, within capacity")
    else:
        a.status = REVIEW
        a.warnings.append(f"Needs planner review: no certified factory has room ({text} with this lot, "
                          f"limit {hard_limit_pct:.0f}%); not bought automatically")
    return a
