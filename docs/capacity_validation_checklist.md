# Capacity validation checklist

## Current behavior

Factory routing checks utilization before adding the proposed lot.
A primary factory below the 85% routing threshold can therefore
receive an order that pushes its projected utilization above 100%.

The capacity ledger records the additional units, but the assignment
decision does not check the resulting utilization before accepting it.

Relevant files:
- engine/planner.py
- engine/rules/assignment.py
- engine/capacity.py
- engine/accounting.py

## Business decisions to confirm

- Does the 85% routing threshold apply before or after adding a lot?
- Is 100% a hard capacity limit for ordinary orders?
- What should happen when neither approved factory has room?
- How should last-chance exceptions be represented?

## Proposed regression cases

These are proposed checks, not completed test results.

| Case | Setup | Expected check |
|---|---|---|
| Primary overload | Capacity 100 units/week, existing load 80, new lot 40 in the same week | Detect projected load of 120% |
| Backup overload | Backup starts below 85%, but the new lot pushes it above 100% | Do not treat the backup as feasible without checking the new load |
| Multiple orders | Two lots compete for the same remaining capacity | Include earlier allocations when checking the next lot |
| Manufacturing spans several weeks | A lot overlaps multiple production weeks | Check every affected week |
| Manual factory switch | A planner moves a lot between factories | Remove its old allocation and check its new allocation |
| Customer hold | A hold reduces a lot's quantity | Recheck country and factory minimums |

## Completion criteria

- [ ] Client routing and capacity policies are recorded.
- [ ] Regression tests use synthetic data and run without client CSVs.
- [ ] Assignment checks include the proposed quantity.
- [ ] Exceptions appear explicitly in validation results.
- [ ] Presentation examples match the implemented behavior.
