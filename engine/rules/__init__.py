"""Spec section 4 rule cascade.

Order (spec): certification and capacity first, then
Rule 1 purchase window -> Rule 5 wholesale exclusion -> Rule 6 last chance
-> Rule 2 15-day grouping -> Rule 3 MOQ/MPQ -> Rule 4 piggyback.
One module per rule; each lot carries a plain-English reason.
"""
