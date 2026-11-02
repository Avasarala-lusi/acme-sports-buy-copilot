# Purchasing Planner Validation Cases

Owner: Dilip Nallamasa
Status: Prepared for execution

## Purpose

Check whether purchasing recommendations follow the agreed business rules.

Expected results below must be checked against the current client decision log and configuration before execution. These cases are not reported as passed until evidence is recorded.

## Execution details

Complete these fields when running the checks:

- Repository commit:
- Data version:
- Configuration:
- Test date:
- Reviewer:

## Cases

### V01: Wholesale demand without a sales order

Setup:
Select a wholesale PR without a matching sales order and without an Early Buy exception. Use a request that is not a last-chance conflict.

Expected:
The request is not automatically purchased under the normal eligibility rule. Its outcome and reason remain visible.

Actual result: Pending
Evidence: Pending

### V02: Required production-start calculation

Setup:
Use a requested delivery date of 2026-06-30, manufacturing lead time of 30 calendar days, and transportation lead time of 10 calendar days.

Expected:
The calculated required production-start date is 2026-05-21. Buying eligibility must also follow the configured buying calendar.

Actual result: Pending
Evidence: Pending

### V03: Grouping at the 15-day boundary

Setup:
Use otherwise eligible requests for the same product and destination with delivery dates January 1, January 16, and January 17. Use strict anchor grouping with a 15-day limit.

Expected:
January 1 and January 16 may form one date group. January 17 must not join that group. Other eligibility and quantity checks still apply.

Actual result: Pending
Evidence: Pending

### V04: Minimum order quantity after a customer hold

Setup:
Use an eligible 350-unit group containing 150 units for the customer being held and 200 units for another customer. Set MOQ to 300.

Expected:
The held customer's demand is removed from the current buying decision. The remaining 200 units trigger a fresh minimum-quantity check and the applicable warning or planning outcome.

Actual result: Pending
Evidence: Pending

### V05: Minimum production quantity

Setup:
Set apparel MPQ to 1,200. Prepare two examples whose quantities satisfy the current agreed MPQ grouping:
- Total of 1,200 units.
- Total of 1,100 units.

Expected:
The 1,200-unit example passes the quantity threshold. The 1,100-unit example remains below the threshold and follows the applicable wait, review, or last-chance exception rule.

Passing MPQ alone does not establish that an order is eligible or feasible.

Actual result: Pending
Evidence: Pending

### V06: Piggyback tolerance boundary

Setup:
Set MOQ to 300 and piggyback tolerance to 5%. Compare eligible groups containing 285 units and 284 units. Provide eligible future requests where required.

Expected:
285 units is within the tolerance and may trigger a search for whole eligible requests to fill the shortfall. 284 units is outside that automatic tolerance.

The tolerance does not mean that 285 units automatically satisfies MOQ.

Actual result: Pending
Evidence: Pending

### V07: Factory certification

Setup:
Select a product and a factory that is not certified for that product. Attempt a factory change.

Expected:
The application rejects the uncertified assignment. Available capacity must not override certification.

Actual result: Pending
Evidence: Pending

### V08: Capacity includes the proposed assignment

Setup:
Use one production week with factory capacity of 1,000 units, existing commitments of 800 units, and an additional assignment of 300 units entirely allocated to that week.

Expected:
Projected utilization is 110%. The assignment cannot be committed to that factory under the 100% hard ceiling. The engine must evaluate permitted alternatives or retain the demand for planner review.

Actual result: Pending
Evidence: Pending

## Recording results

For each executed case, record:

- Planning run:
- PR or lot IDs:
- Steps performed:
- Expected result:
- Actual result:
- Status: Pass / Fail / Blocked
- Evidence location:
- Related issue or fix:
- Reviewer:

Keep private client data out of public attachments. Use approved evidence locations.

## Completion criteria

- All eight cases have been executed or have a documented blocker.
- Expected results match the current agreed rules.
- Failures include reproducible steps.
- Corrected cases have been retested.
- A teammate has reviewed the results.
