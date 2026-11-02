# Export Validation Checklist

Owner: Dilip Nallamasa
Status: Not executed

## Purpose

Verify that exported buying plans match the effective plan shown in
the application, including saved planner decisions.

## Test setup

Record before testing:

- Repository commit:
- Data version:
- Configuration:
- Planning run:
- Selected PR or lot IDs:
- Test date:

Use a temporary decision store or an isolated test copy so testing
does not overwrite another planner's saved decisions.

## Checks

### 1. Automatic plan

- [ ] Select a buying run with no manual changes.
- [ ] Export the single-run CSV and XLSX.
- [ ] Compare purchased PRs, quantities, factories, and proposed dates
      with the corresponding application records.
- [ ] Confirm that totals reconcile.

### 2. Saved No-Go decision

- [ ] Save No-Go for a selected lot.
- [ ] Confirm the affected requests are not exported as purchases.
- [ ] Confirm unrelated purchases remain correctly represented.
- [ ] Compare the updated application totals with the export.

### 3. Saved factory change

- [ ] Select a certified alternative factory.
- [ ] Save the change and inspect the resulting decision.
- [ ] Confirm the export matches the effective assignment.
- [ ] Compare proposed dates and quantities with the application.
- [ ] Confirm any rejected change is not exported as an accepted purchase.

### 4. Customer hold

- [ ] Save a hold for one customer in the selected window.
- [ ] Confirm held demand is not exported as a purchase in that window.
- [ ] Check remaining quantities and the resulting planning outcome.
- [ ] Confirm the export reflects any regrouping or minimum-quantity effects.

### 5. Single-run and all-run consistency

- [ ] Export the complete plan.
- [ ] Filter it to the same buying run.
- [ ] Compare purchase records with the single-run export.
- [ ] Check identifiers and quantities for unexpected duplicates.

### 6. Undo

- [ ] Revert the test decisions.
- [ ] Export the plan again.
- [ ] Confirm purchase records match the original plan,
      excluding non-business metadata such as generation timestamps.

## Results

| Check | Expected result | Actual result | Status | Evidence |
|---|---|---|---|---|
| Automatic plan | App and exports reconcile | Pending | Not run | Pending |
| No-Go | Cancelled demand excluded from purchases | Pending | Not run | Pending |
| Factory change | Effective assignment matches | Pending | Not run | Pending |
| Customer hold | Current-window purchases reflect hold | Pending | Not run | Pending |
| All-run consistency | Same-run records reconcile | Pending | Not run | Pending |
| Undo | Original purchase records restored | Pending | Not run | Pending |

## Reporting a mismatch

Record the reproduction steps, affected identifiers, expected result,
actual result, and related issue. Keep private client data in approved
locations.

Do not mark a check as passed until it has been executed and reviewed.
