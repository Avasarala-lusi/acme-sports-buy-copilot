# Capacity validation checklist

## Current behavior

Factory routing checks the projected utilization **including the proposed lot**. For each certified option,
the load is the highest weekly utilization over the lot's production weeks with the lot added
(`CapacityLedger.utilization_with`).

- The lot stays on its primary factory while the projected load is below the 85% routing threshold.
- Otherwise it goes to the first certified backup in the chain whose projected load is below 85%.
- If no option is below 85%, the less-loaded option is used only while it stays within the 100% hard limit,
  with a warning.
- Beyond the hard limit, the lot is not bought: it goes to **planner review**. Last-chance lots are the
  exception (client: warn, don't block) and are bought with an explicit over-capacity warning.

Every lot records its load before and after (`util_before_pct`, `util_after_pct`) and a capacity status:
Within capacity, Above threshold within capacity, Over capacity (last chance), or Needs planner review.

Relevant files:
- engine/planner.py
- engine/rules/assignment.py
- engine/capacity.py
- engine/accounting.py
- config/thresholds.yaml (`backup_threshold_pct`, `hard_limit_pct`, `when_no_capacity`)

## Business decisions to confirm

| Question | Current setting | Status |
|---|---|---|
| Does the 85% routing threshold apply before or after adding a lot? | After: the projected load includes the lot | Implemented; confirm with the client |
| Is 100% a hard capacity limit for ordinary orders? | Yes (`hard_limit_pct: 100`) | Open: is overtime possible? |
| What should happen when neither approved factory has room? | Planner review, not bought (`when_no_capacity: planner_review`) | Open: alternatives are a third certified factory, a later date or buy with a warning |
| How should last-chance exceptions be represented? | Bought with an over-capacity warning and status "Over capacity (last chance)" | Follows the client's warn, don't block |

## Regression cases

| Case | Setup | Expected check | Covered by |
|---|---|---|---|
| Primary overload | Capacity 1,000 units/week, existing load 840, new lot 500 | Projected load 134%, lot sent to planner review | `tests/test_rules.py::test_review_case_84_percent_plus_new_lot` |
| Backup overload | Backup below 85% before the lot, above the limit with it | Backup not treated as feasible | `tests/test_rules.py::test_chain_with_no_room_goes_to_review`, `test_chain_walks_to_the_next_backup_with_room` |
| Multiple orders | Lots compete for the same remaining capacity | Earlier allocations count when checking the next lot | `tests/test_planner.py::test_no_factory_week_over_limit_except_last_chance`, `test_lots_record_load_including_the_lot` (full plan) |
| Manufacturing spans several weeks | A lot overlaps multiple production weeks | Every affected week is checked | `tests/test_rules.py::test_ledger_spreads_units_over_manufacturing_weeks` |
| Manual factory switch | A planner moves a lot between factories | Old allocation removed, new allocation checked | `tests/test_scenarios.py::test_swap_capacity_is_measured_after_the_move` |
| Customer hold | A hold reduces a lot's quantity | Country and factory minimums rechecked | `tests/test_scenarios.py::test_hold_rechecks_minimums_after_the_fix`, `test_hold_fix_never_pulls_the_held_customer_or_reuses_demand` |

Tests in `tests/test_rules.py` use synthetic data and run without the client CSVs. Tests in `tests/test_planner.py`
and `tests/test_scenarios.py` run on the full plan and need the client data in `data/raw/`.

## Completion criteria

- [ ] Client routing and capacity policies are recorded (current settings are in `config/thresholds.yaml`; the
      hard limit and the no-room policy await client confirmation).
- [x] Regression tests use synthetic data and run without client CSVs (assignment and ledger cases).
- [ ] A synthetic test for lots competing for the same capacity (currently covered only by the full-plan tests).
- [x] Assignment checks include the proposed quantity.
- [x] Exceptions appear explicitly in validation results (capacity status per lot; no factory week above the
      limit except labelled last-chance lots).
- [ ] Presentation examples match the implemented behavior (refresh the demo example for data v5).
