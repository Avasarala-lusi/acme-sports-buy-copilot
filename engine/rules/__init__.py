"""Spec section 4 rule cascade, one module per rule.

Order used by the planner:
  Rule 5 wholesale exclusion -> Rule 6 last chance -> Rule 1 purchase window
  -> Rule 2 15-day grouping -> Rule 3 MOQ (+ Rule 4 piggyback)
  -> certification and capacity routing -> Rule 3 MPQ (+ Rule 4 piggyback).
Capacity routing needs lot quantities, so it runs after grouping; certification is
enforced at assignment and re-checked on every output.
"""
