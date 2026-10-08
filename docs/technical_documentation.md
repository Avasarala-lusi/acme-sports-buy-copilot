# Acme Sports Buy Planner: technical documentation (Phase 1)

Team Vantage · University at Buffalo × Globant · October 2026

This document covers the Phase 1 scope agreed in the Week 2 scoping review: a weekly buy-plan engine that applies
the specification's rules, a what-if simulator, capacity-driven pull-forward analysis, the trend notebook, the
populated output table and the validation checks. Phase 2 (forecast-driven network optimisation, delay risk and RL)
builds on this engine.

## 1. How to run

```bash
pip install -r requirements.txt
# put the nine ACME CSVs in data/raw/ (client data is never committed)
python scripts/run_plan.py                 # plan all 100 runs, write outputs/
streamlit run app/streamlit_app.py         # planner app (select week, plan, test a change, export)
uvicorn api.main:app --reload              # REST API for a custom front end
python notebooks/build_trend_notebook.py   # rebuild and execute the trend notebook
python scripts/build_worked_examples.py     # regenerate docs/worked_examples.md
pytest                                     # 58 tests
```

The first full plan takes about 8 seconds; the planned engine is cached in `outputs/` and reloads in about 2 seconds.
The cache key includes the config and the engine source, so it is rebuilt automatically when either changes.

## 2. Code layout

| Path | Purpose |
|---|---|
| `config/thresholds.yaml` | Every threshold and every client decision; nothing is hardcoded in the engine |
| `engine/data_loader.py` | Loads and validates the nine tables; reports data issues instead of failing |
| `engine/calendar.py` | Monthly buying windows and production weeks |
| `engine/capacity.py` | Rolling capacity ledger built from our own assignments |
| `engine/rules/` | One module per rule: timing (Rule 1), grouping (Rule 2), quantities (Rules 3–4), exclusion (Rules 5–6), assignment (certification and capacity) |
| `engine/planner.py` | Runs the rule cascade one MRP run at a time and carries open demand forward |
| `engine/accounting.py` | Complete-accounting check and rule-violation check |
| `engine/metrics.py` | KPIs and the comparison with the as-is reference |
| `engine/pull_forward.py` | Capacity-driven pull-forward analysis (spec 3.3) |
| `engine/output.py` | `fact_buy_plan_suggestions` and other output files; engine cache |
| `engine/overrides.py` | Saved manual Go/No-Go decisions, applied on top of the automatic plan |
| `sim/scenarios.py` | The what-if scenarios (spec section 5) |
| `app/streamlit_app.py` | Planner app |
| `api/main.py` | FastAPI service |
| `notebooks/` | Trend analysis notebook and its builder |
| `tests/` | Unit, integration and scenario tests |

## 3. Data findings

All of these are also listed in the app's **Data & checks** tab.

| Finding | Handling |
|---|---|
| 100 weekly runs supplied; the spec mentions 52 | Client decision: use all 100 weeks |
| 336 of 600 factory-weeks above 100% utilisation (max 1,736%) | Client reviewing the source; the engine ignores the static table and uses its own rolling ledger |
| 9,946 DTC sales orders have no customer record | Client decision: treat DTC as one bulk customer |
| Article-level and factory-level backups differ for 27 of 40 articles | Open question; article-level used (config `backup_source`), since the supplied PR data follows it 100% |
| The 3 C-rated customers have no sales orders | Raised with the client; hold scenario demonstrated with B-rated customers and DTC |
| No promised vs actual delivery dates | Delay risk is simulated in Phase 2, not predicted |
| `channel_id` stored as 1/2, not "01"/"02" | Normalised on load |
| Spec example says ID03 costs 15% more than VN01; the factory table says 0.95 vs 1.10 | Factory table used; flagged to the client |

All keys are unique, every requisition references a known article, every supplied assignment is certified, and every
RDD is after its MRP run date.

## 4. Client decisions applied (Week 2 review)

- Use all 100 weeks.
- One buying window per month, in the third week (cutoff on the 21st, configurable).
- Capacity is recomputed as a rolling window from our own assignments.
- A unique PR ID is a unique demand; demand is never bought twice.
- Last-chance conflicts raise a warning rather than blocking the plan.
- DTC is one customer.

## 5. The rule cascade

Each MRP run is processed in order. The open pool is every requisition not yet decided: new ones from this run plus
those carried from earlier runs.

1. **Rule 5, wholesale exclusion** (new demand): wholesale requisitions with no sales order get the final outcome
   `FUTURE_FORECAST`, unless the article is Early Buy (always bought) or last chance.
2. **Rule 6, last chance**: every open requisition of a last-chance article is due now, regardless of dates.
3. **Rule 1, purchase window**: release date = RDD − manufacturing lead time − transport lead time (at the primary
   factory). A requisition is due when its release date falls before the *next* monthly window; otherwise it waits.
4. **Rule 2, grouping**: due requisitions are grouped by article and market; RDDs in a lot are within 15 days of the
   lot's earliest RDD (`anchor`), or of each other (`chain`, configurable, open question).
5. **Rule 3, MOQ** (300 per market per article). If a lot is within 5% below MOQ, **Rule 4 piggyback** pulls whole
   future requisitions of the same article and market, earliest RDD first, and records the source window.
   A lot still short either waits for the next run (if production could still start on time) or becomes
   `UNRESOLVED_MOQ`. Last-chance lots are bought with a warning.
6. **Factory assignment** (certification and capacity): see section 6.
7. **Rule 3, MPQ** (1,200 apparel, 2,400 footwear) per article per factory within the run, with the same Rule 4
   piggyback, wait or `UNRESOLVED_MPQ` logic. Assignment and the MPQ check repeat until stable.

Each bought lot records a plain-English reason for every rule that applied, and warnings for anything the planner
should review. All engine decisions are `decision_type = auto`; what-if changes are `manual`.

### Outcomes

Every requisition ends with exactly one outcome:

| Outcome | Meaning | Requisitions | Units |
|---|---|---|---|
| `BOUGHT` | In a purchase lot | 15,982 | 11,815,627 |
| `FUTURE_FORECAST` | Rule 5: wholesale forecast without an order | 6,375 | 4,326,491 |
| `UNRESOLVED_MOQ` | Below MOQ and could not wait | 993 | 160,737 |
| `UNRESOLVED_MPQ` | Below MPQ and could not wait | 598 | 291,793 |
| `OPEN` | Not yet due at the end of the data (still waiting) | 1,014 | 580,803 |

Unresolved demand is shown separately in the app and is never treated as a feasible purchase.

## 6. Factory assignment and the capacity ledger

- The primary and backup factories come from `dim_article_master` (configurable); certification is always read from
  `dim_factory_article_matrix`.
- A lot's production starts at the later of its release date and the PO execution date, and its units are spread
  evenly over its manufacturing weeks in the ledger.
- If the primary is at or above 85% in those weeks, the lot goes to the backup, provided the backup is certified.
- If both are at or above 85%, the lot goes to the less-loaded factory with a **capacity-conflict warning**
  (open question with the client).
- Lead times: a requisition's own lead times are used at its supplied factory; at any other factory we use the
  midpoint of that factory's min/max range.
- Cost = quantity × unit cost × the assigned factory's cost multiplier. Each lot also shows the cost delta versus
  its primary factory.

Across the 100 runs: 8,799 lots, 2,936 routed to a backup, 197 with piggyback. 4,513 lots carry a capacity-conflict
warning: total demand (17.2M units) exceeds what the six factories can produce at 85% over the period, so conflicts
are a property of the data, made visible rather than hidden.

## 7. What-if scenarios

All scenarios work on a copy of one run's plan.

| Scenario | Output |
|---|---|
| Hold a customer | Units removed per lot and size, NSV at risk, new lot quantity |
| Check minimums (MOQ cascade) | Lots that fall below MOQ after a hold, with a suggested same-market piggyback fix and the recalculated quantity and RDD |
| Delay production | Shift a factory's production by N days: new arrival dates, late lots, late units, affected customers and NSV at risk |
| Switch factories | Certification check, cost-multiplier and lead-time deltas, new arrival date, MOQ status and target-factory load |

### Manual decisions (Go/No-Go)

The spec requires the tool to distinguish automatic rules from manual overrides. The engine's plan is never
changed; planner decisions are saved separately (`outputs/overrides.json`) and applied on top:

| Override | Effect |
|---|---|
| Lot decision: Buy / No-Go / Delay | No-Go and Delay lots are left out of the exported buy plan |
| Factory switch (certified factories only) | Cost, lead time and arrival recalculated at the new factory |
| Customer hold (applied from the what-if tab) | That customer's units removed from every lot; a lot with nothing left becomes No-Go; lots falling below MOQ get a warning |

Every changed lot is marked `decision_type = manual` with a note explaining the change, KPIs show the change
against the automatic plan, and a week can be reverted to the automatic plan in one click.

## 8. Pull-forward analysis (spec 3.3)

For a run, the engine projects each factory's load over the current and next four monthly windows: committed lots
from the ledger plus open demand placed at its primary factory. Windows at or above 85% generate recommendations,
grouped by article and market: pull into the earliest lower-load window, check MOQ for that market, and show the
extra cost of the alternative (routing to the backup in the overloaded window).

## 9. Validation (success criteria from the scoping review)

| Check | Result |
|---|---|
| Valid recommendations: certified factory, single article and market, MOQ met or warned, grouping window respected | 0 violations |
| Complete accounting: every requisition has one outcome, no requisition in two lots, units add up | Passed (24,962 requisitions, 17,175,451 units) |
| Correct scenarios: hand-calculated checks | Passed (tests/test_scenarios.py); worked examples in `docs/worked_examples.md` |
| Comparison with a reference plan | See below |

Tests: `pytest` runs 58 tests: rule unit tests, integration tests on the full plan, scenario hand checks,
manual-decision tests, data checks, and headless app tests. In addition, a full app sweep exercised all
100 weeks and every scenario (1,694 interactions) and the save, apply and revert buttons on every tenth week
(640 interactions), with no failures.

`docs/worked_examples.md` walks through real lots step by step (purchase window, grouping, MOQ/MPQ, capacity
routing, piggyback, wholesale exclusion, customer hold, delay, factory switch, accounting). The script that
writes it re-checks every number against the engine.

### Comparison with the as-is reference

The as-is reference uses the factory assignments in the supplied data and buys every requisition in the run it
appears, with no rules. The agreed reference plan is still to be confirmed with the client.

| Metric (all 100 runs) | Our plan | As-is |
|---|---|---|
| Units bought | 11.82M | 17.18M |
| Production cost | $1.154B | $1.646B |
| Cost per unit | $97.66 | $95.86 |
| On-time share of units bought | 95.8% | 96.9% |
| Routed to backup | 33% of lots | 58% of requisitions |
| Unresolved units (shown separately) | 0.45M | n/a (no rules applied) |

The as-is plan buys everything immediately and ignores MOQ (3,196 article-market lots below 300) and the wholesale
exclusion rule, so its volumes are not comparable one to one. Our plan follows the rules and is slightly more
expensive per unit because capacity routing does not yet look for the cheapest certified factory; that is the main
target of the Phase 2 network optimiser.

## 10. Deviations and assumptions

| Topic | Choice | Why |
|---|---|---|
| Order of rules | Capacity routing runs after grouping | Routing needs lot quantities; certification is still enforced on every assignment |
| Buying window | Monthly, cutoff on the 21st | Client decision (third week); configurable |
| Capacity source | Rolling ledger, units spread over manufacturing weeks | Client decision; the static table exceeds 100% in 336 weeks |
| Both factories over 85% | Less-loaded factory plus warning | Open question; never blocks the plan |
| Lots below MOQ/MPQ | Wait for the next run if production can still start on time | Avoids declaring demand unresolved too early; configurable |
| Last chance | Includes forecast-only demand; bought below minimums with a warning | Catalogue closure; client said warn, don't block |
| Piggyback | Whole requisitions, same market only | Keeps accounting exact and respects per-market MOQ |
| MPQ scope | Per article per factory per run | Spec: factory level across markets in the same window |
| Suggested RDD | Earliest RDD in the lot, or the expected arrival if later | Gives the planner a realistic date |
| Lead time at another factory | Midpoint of that factory's range | No per-requisition lead time exists for factories other than the supplied one |

## 11. Open questions for the client

1. Article-level or factory-level backup: which is authoritative?
2. Rule 2: anchor on the earliest RDD, or allow chaining?
3. When both primary and backup exceed 85%: third factory, delay, or flag?
4. The reference plan and the weighting of cost, on-time units and unresolved demand.
5. Delivery history or permission to use public delay data (Phase 2).
