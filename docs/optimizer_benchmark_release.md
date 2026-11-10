# Rolling cost/service planning and planner benchmark

Updated November 5, 2026. This supplements the October 30 core/forecast release.

## What is released

The cost/service page and benchmark use a read-only, automatic historical replay. They do not submit a PO,
replace the Buy Plan, edit saved planner decisions or include manual scenarios. The optimizer makes a joint
factory choice within each formal buying window; it never optimizes all future windows in one solve.

Risk simulation, disruption drill, data-health extensions and plain-English questions remain disabled.
The old `Network` and `_legacy_whole_history_solve` implementation is retained only for the disabled disruption
prototype. It is not used by either released page; migrate and validate that prototype before enabling it.

## Rules before preferences

`RollingOptimizer` inherits the normal planner's intake, eligibility, due-date handling, grouping, quantity
piggyback, final MPQ gate, unresolved-demand retention and chronological run loop.

- Only requests received by the current run can enter its factory assignment.
- Prior purchases remain reserved in the production ledger. The solver sees remaining weekly capacity,
  calculated with the same calendar-day lead time and business-day production allocation as the core.
- Each normal market lot must meet MOQ independently. Last-chance quantity warnings remain explicit exceptions.
- MPQ uses the configured article/factory/purchase-window and RDD-span policy, with category thresholds.
  The default remains `rdd_band`; the optimizer does not silently switch to broader purchase pooling.
- A selected last-chance lot can trigger the shared MPQ warning exception; merely having an unselected
  last-chance candidate does not waive MPQ for other purchases.
- Factory certification is mandatory. Accepted pull-forward targets retain their stricter destination headroom.
- Purchase admission is fixed lexicographically: last chance, release date, RDD, descending sales value, order
  backing, then deterministic PR identity. A large normal order cannot displace feasible last-chance demand.
- After admission, the slider chooses factory assignments using normalized production cost and **planned
  late units**. No assumed delivery probability is used in this release. Cost-focused/service-focused labels
  are preferences, not promises of the lowest cost per bought unit or global historical optimality.

Priority is solved in small binary blocks, with earlier admission choices fixed before proceeding. A solver
that cannot prove its result falls back to the core routing procedure and records that fallback. Such a run
is not reported as fully validated, and is not eligible to recommend a setting based on its tuning results.

The shared cascade can attempt the configured 5% MPQ top-up before its final strict MPQ gate. Candidate MPQ
bands are conservative fixed partitions: a skipped candidate can prevent otherwise possible pooling. This
can reduce purchases; it cannot justify an invalid wider RDD span. Repeated cascade passes and the final
quantity gate can affect the final allocation. Do not claim a globally optimal six-rule plan.

## Routing policy

The rule engine walks the configured primary/backup chain. The optimizer considers all certified factories
jointly as an alternative recommendation policy. The 85% threshold remains a soft warning and 100% is a hard
ceiling. This comparison does not silently replace the core routing policy or authorize a saved purchase.

## Comparable demand and outcomes

Every approach is evaluated on the same complete eligible demand population, not only demand that happened
to form a bought/review lot. Requests excluded by confirmation rules are disclosed separately, with total
supplied units, so all demand is accounted for.

For every cohort: eligible units = planned on-time units + planned late units + unbought units. Report total
production cost and cost per bought unit alongside those quantities. Excluded/held/unresolved requests are not
silently treated as purchased or profitable. Saved manual decisions are outside this automatic reference.

Cohorts use the PR's intake season so a different purchase date cannot move a difficult request out of a
method's denominator. A cohort's capacity figures include the complete committed ledger in its production
weeks, including other seasons sharing those weeks. Combined-period KPIs are calculated by the backend;
the UI does not add overlapping seasonal capacity counts.

The supplied-assignment baseline uses the intake run's recorded PO date, including weekly dates. The rule
engine and optimizer use formal MID/EOM purchases. All loads use the same production allocation, but these
purchase-timing assumptions differ. Label the supplied plan as a reference, disclose its overloads, and do not
attribute all baseline differences to better factory selection.

## Earlier-only setting selection

For each slider setting, replay the earlier tuning seasons and capture its metrics **before** processing any
test-period request. Then continue that replay with the earlier commitments intact. Select the setting from
captured tuning metrics only. A regression test changes later demand drastically and checks that earlier
purchases, tuning results and setting selection stay unchanged.

The existing marginal-cost selection rule is a team heuristic, not a client-approved profit model: prefer
extra planned on-time units while their marginal production cost is no more than the previous cost per bought
unit. Test results do not choose the setting. No subsequent tuning on the later results is implied.

Small per-setting JSON caches allow a long calculation to resume. Final and per-setting caches use new names
and hash code/config/input metadata, so older whole-history benchmark numbers are not reused. The first full
calculation can take 15–25 minutes on a laptop (hardware and solver complexity matter). No claim of improvement is accepted until all settings' validations pass.

## Validation

The focused release tests reproduce independent market MOQ, RDD-span MPQ, category thresholds, last-chance and
release/RDD/value priority, certification/confirmation gates, previous commitments, service versus cost choices,
future-demand independence and full-population reconciliation. Full-data validation and measured results are
recorded in the local decision/report log after completion. Old optimizer percentages are superseded.

## Measured V5 results (November 5)

All five settings passed accounting and bought-lot rule checks, with no factory-week over 100% and no solver fallbacks. The earlier-only heuristic selected weight **0.25**.

| Measure | Rule engine | Selected optimizer |
|---|---:|---:|
| All eligible units planned on time | 38.76% | 44.28% |
| Units bought | 6,481,756 | 7,267,986 |
| Units planned late | 1,613,534 | 1,705,252 |
| Unbought / pending units | 6,079,509 | 5,293,279 |
| Production cost per bought unit | $89.55 | $86.44 |
| Total production cost | $580,459,881.22 | $628,221,725.27 |
| Units at backup factories | 11.50% | 59.01% |

Later-period eligible on-time share: **33.57% → 36.57%**. The common eligible population is 17,845 PRs / 12,561,265 units. The remaining 4,993,378 supplied units are confirmation-ineligible and separately disclosed.

The optimizer buys more and has a lower production cost per bought unit, but total spending, late units and backup use increase. This is a trade-off for planner/client review, not proof of profit improvement or universal superiority. The optimizer routing policy is an alternative recommendation; it does not replace the core chain policy.

Validation: **159 core/release tests passed, 7 deferred prototype tests deselected**, one existing Starlette/httpx deprecation warning. Production frontend build and dependency consistency checks passed. The complete validation run, including cold base initialization and two parallel replay workers, took about 15 minutes; first uncached UI computation may be longer. Cached results are fast.
