"""Rule 3: MOQ / MPQ checks, and Rule 4: piggyback (quantity pull-forward)."""

OK, PIGGYBACK, SHORT = "ok", "piggyback", "short"


def quantity_status(qty: float, threshold: float, tolerance_pct: float) -> str:
    """ok if qty meets the threshold; piggyback if within tolerance below it; else short."""
    if qty >= threshold:
        return OK
    if qty >= threshold * (1 - tolerance_pct / 100):
        return PIGGYBACK
    return SHORT


def pick_to_fill(shortfall: float, candidates: list[tuple[str, float]]) -> list[str]:
    """Take whole candidate requisitions (already in priority order) until the shortfall is met.

    Returns the chosen ids, or an empty list if the candidates cannot cover the shortfall.
    """
    chosen, total = [], 0.0
    for cid, qty in candidates:
        if total >= shortfall:
            break
        chosen.append(cid)
        total += qty
    return chosen if total >= shortfall else []


def mpq_for(category: str, mpq: dict) -> int:
    return mpq[category]
