"""Rule 5: wholesale forecast exclusion, and Rule 6: last chance."""

WHOLESALE = "01"
DTC = "02"


def forecast_excluded(channel_id: str, has_order: bool, early_buy: bool) -> bool:
    """Wholesale demand with no confirmed sales order moves to Future, unless Early Buy."""
    return channel_id == WHOLESALE and not has_order and not early_buy


EXCLUSION_REASON = "Rule 5: wholesale forecast with no confirmed sales order, moved to Future"
EARLY_BUY_REASON = "Rule 5 exception: Early Buy article, purchased without a confirmed order"
LAST_CHANCE_REASON = "Rule 6: last-chance article, buy all outstanding demand now"
