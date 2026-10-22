# Acme Sports Buy Planner: technical documentation

> Historical description below predates the latest client-rule alignment. Use
> `docs/client_rule_updates.md` and the settings view for current behavior. Old 23-window counts,
> numeric comparisons and last-chance overload exceptions are not current validation results.

Team Vantage · University at Buffalo × Globant · October 2026

This document covers the scope agreed with the client: a buy-plan engine (weekly drafts, monthly purchases) that applies
the specification's rules, a what-if simulator, capacity-driven pull-forward analysis, the trend notebook, the
populated output table and the validation checks. Planned extensions (forecast-driven network optimisation,
delay risk and learned thresholds) build on this engine.

## 1. How to run

Requires Python 3.10+ and Node.js 18+. The React web app is the project's user interface.

```bash
pip install -r requirements.txt
# put the nine ACME CSVs in data/raw/ (client data is never committed)
python scripts/run_plan.py                 # plan all 100 runs, write outputs/
(cd frontend && npm install && npm run build)  # build the React web app
uvicorn api.main:app --port 8000           # API and web app: http://localhost:8000/ui/
jupyter notebook notebooks/trend_analysis.ipynb  # the five trend analyses
python scripts/build_worked_examples.py     # regenerate docs/worked_examples.md
pytest                                     # run the remaining automated tests
```

For front-end development, keep the API running and run `npm run dev` in `frontend/` from
a second terminal. Open `http://localhost:5173`. See `frontend/README.md` for details.

The first full plan takes about 25 seconds (100 runs, including a draft for each of the 77 weeks between buying
windows); the planned engine is cached in `outputs/` and reloads in a few seconds.
The cache key includes the config and the engine source, so it is rebuilt automatically when either changes.

## 2. Code layout

| Path | Purpose |
|---|---|
| `config/thresholds.yaml` | Every threshold and every client decision; nothing is hardcoded in the engine |
| `engine/data_loader.py` | Loads and validates the nine tables (customers, backup chain, certification); reports data issues instead of failing |
| `engine/calendar.py` | Monthly buying windows (third-week PO day) and production weeks |
| `engine/capacity.py` | Rolling capacity ledger built from our own assignments |
| `engine/rules/` | One module per rule: timing (Rule 1), grouping (Rule 2), quantities (Rules 3–4), exclusion (Rules 5–6), assignment (certification and capacity) |
| `engine/planner.py` | Takes in demand every week, previews the next window in draft weeks, commits purchases in buying runs, carries open demand forward |
| `engine/accounting.py` | Complete-accounting check and rule-violation check |
| `engine/metrics.py` | KPIs and the comparison with the as-is reference |
| `engine/pull_forward.py` | Capacity-driven pull-forward analysis (spec 3.3) |
| `engine/output.py` | `fact_buy_plan_suggestions` and other output files; engine cache |
| `engine/overrides.py` | Saved manual Go/No-Go decisions, applied on top of the automatic plan |
| `sim/scenarios.py` | The what-if scenarios (spec section 5) |
| `frontend/` | React planner web app |
| `api/main.py` | FastAPI service |
| `notebooks/` | Trend analysis notebook: the five required analyses |
| `tests/` | Unit, integration and scenario tests |

## 3. Data findings

The engine runs on **data v5** (25,141 requisitions, 17.55M units, 17,845 sales orders). All findings are also listed
in the app's **Data & checks** view.

| Finding | Handling |
|---|---|
| 100 weekly runs supplied; the spec mentions 52 | Client decision: use all 100 weeks |
| 317 of 600 factory-weeks above 100% utilisation in the static table (max 2,303%) | Client reviewing the source; the engine ignores the static table and uses its own rolling ledger |
| Factory-level backups form an acyclic chain ending at CN04 (v5; v4 had a VN01 → ID03 → CN04 loop and BD02 ↔ IN06) | The engine walks the chain (`backup_source: factory_chain`); every supplied v5 backup assignment follows it |
| Article-level and factory-level backups differ for 30 of 40 articles | Article-level routing remains available as a setting; see the comparison in section 6 |
| Every requisition now names its customer (v5); DTC demand belongs to ACME's own channels and three key accounts | DTC is no longer one anonymous customer; holds work per named account |
| The 3 C-rated customers now have 485 orders (about $66M) | Used for the credit-hold scenario |
| No promised vs actual delivery dates | Delay risk will be simulated in a planned extension, not predicted |
| `channel_id` stored as 1/2, not "01"/"02" | Normalised on load |
| Spec example says ID03 costs 15% more than VN01; the factory table says 0.95 vs 1.10 | Factory table used; flagged to the client |

All keys are unique, every requisition references a known article and customer, every supplied assignment is
certified, sales orders and requisitions name the same customer, and every RDD is after its MRP run date. The
previous version's data is kept locally in `data/raw_v4/` for comparison.

## 4. Client decisions applied

- Use all 100 weeks.
- One buying window per month, in the third week. The window is the PO execution day that falls on days 15-21
  (our reading of "third week", configurable); the run with that PO date is the month's buying run.
- Capacity is recomputed as a rolling window from our own assignments.
- A unique PR ID is a unique demand; demand is never bought twice.
- Last-chance conflicts raise a warning rather than blocking the plan.
- DTC is one customer (made for anonymous DTC ids; superseded by data v5, which names every DTC account).

## 5. The rule cascade

### Weekly drafts, monthly purchases

The 100 weekly MRP runs are processed in order, and every run takes in its new demand. Of the 100 runs, 23 are
**buying runs** (their PO date is the third-week window date). Only buying runs commit purchases, reserve
factory capacity and close requisitions.

The other 77 runs are **draft weeks**: the engine runs the full cascade as if the next window opened with the
demand known that week, shows the result, and then restores its state. A draft changes nothing; it lets planners
see the coming purchase build up. Draft lots are numbered `D001…`, committed lots `L001…`. Go/No-Go decisions,
holds and factory switches are saved only in buying runs.

### The cascade

The open pool is every requisition not yet decided: new ones plus those carried from earlier runs.

1. **Rule 5, wholesale exclusion** (applied as demand arrives, every week): wholesale requisitions with no sales
   order get the final outcome `FUTURE_FORECAST`, unless the article is Early Buy (always bought) or last chance.
2. **Rule 6, last chance**: every open requisition of a last-chance article is due in this window, regardless of dates.
3. **Rule 1, purchase window**: release date = RDD − manufacturing lead time − transport lead time (at the primary
   factory). A requisition is due when its release date falls before the *next* buying window; otherwise it waits.
4. **Rule 2, grouping**: due requisitions are grouped by article and market; RDDs in a lot are within 15 days of the
   lot's earliest RDD (`anchor`), or of each other (`chain`, configurable, open question).
5. **Rule 3, MOQ** (300 per market per article). If a lot is within 5% below MOQ, **Rule 4 piggyback** pulls whole
   future requisitions of the same article and market, earliest RDD first, and records the source window.
   A lot still short either waits for the next window (if production could still start on time) or becomes
   `UNRESOLVED_MOQ`. Last-chance lots are bought with a warning.
6. **Factory assignment** (certification and capacity): see section 6.
7. **Rule 3, MPQ** (1,200 apparel, 2,400 footwear) per article per factory within the buying window, with the same
   Rule 4 piggyback, wait or `UNRESOLVED_MPQ` logic. Lots sent to planner review do not count towards a factory's
   total. Assignment and the MPQ check repeat until stable.

Each bought lot records a plain-English reason for every rule that applied, and warnings for anything the planner
should review. All engine decisions are `decision_type = auto`; what-if changes are `manual`.

### Outcomes

Every requisition ends with exactly one outcome:

| Outcome | Meaning | Requisitions | Units |
|---|---|---|---|
| `BOUGHT` | In a purchase lot committed in a buying run | 9,685 | 7,111,422 |
| `PLANNER_REVIEW` | In a lot no certified factory had capacity for; not bought until a planner decides | 5,629 | 4,554,483 |
| `FUTURE_FORECAST` | Rule 5: wholesale forecast without an order | 6,416 | 4,336,027 |
| `UNRESOLVED_MOQ` | Below MOQ and could not wait for the next window | 1,156 | 192,066 |
| `UNRESOLVED_MPQ` | Below MPQ and could not wait for the next window | 649 | 361,615 |
| `OPEN` | Not yet due at the end of the data (still waiting) | 1,606 | 999,030 |

Unresolved and review demand is shown separately in the app and is never treated as a feasible purchase.

## 6. Factory assignment and the capacity ledger

- The primary factory comes from `dim_article_master`. Backups follow the factory-level chain from
  `dim_factory_master` (`backup_source: factory_chain`): the primary's backup, then that factory's backup, and so on
  to CN04, the last resort. Article-level backups (`article`) and a single factory-level step (`factory`) are the
  alternatives. Certification is always read from `dim_factory_article_matrix`; uncertified backups are skipped.
- A lot's production starts at the later of its release date and the buying window's PO date, and its units are
  spread evenly over its manufacturing weeks in the ledger. Only committed lots are added to the ledger.
- **Every capacity check includes the lot itself**: the load of a factory is its busiest production week *with the
  lot added*. A lot stays on its primary while that is below 85%; otherwise it goes to the first certified backup in the
  chain that stays below 85% with the lot.
- If neither is below 85%, the less-loaded certified option is used only while it stays within the factory limit
  (100%, configurable), with a warning.
- If no certified option fits within the limit, the lot is **not bought**: it is marked "Needs planner review"
  (`when_no_capacity: planner_review`). A planner can approve it, switch its factory or reject it.
- Last-chance lots are the only exception (client: warn, don't block): they are bought and labelled
  "Over capacity (last chance)", with a warning that extra capacity must be agreed.
- Lead times: a requisition's own lead times are used at its supplied factory; at any other factory we use the
  midpoint of that factory's min/max range.
- Cost = quantity × unit cost × the assigned factory's cost multiplier. Each lot also shows the cost delta versus
  its primary factory, and the factory load before and after the lot.

Across the 23 buying windows: 7,310 lots, of which 5,268 are bought (804 on a backup, 97 with piggyback) and 2,042
need planner review. Of the bought lots, 3,730 are below 85% with the lot, 1,381 are between 85% and the limit, and
157 are last-chance lots over capacity. No factory week is above 100% except through those labelled last-chance
lots (78 of 671 factory-weeks, at most 112.1%). Of the backup moves, 462 end at CN04, 254 at ID03, 80 at BD02 and
8 at IN06. Total demand exceeds what the six factories can make, so the review queue is a property of the data,
made visible instead of hidden.

**Backup source comparison (data v5, all runs).** Walking the factory chain buys 7.11M units and leaves 4.55M for
review; article-level backups would buy 7.61M and leave 3.98M. The chain sends most overflow towards CN04, which is
itself the most loaded factory, while article-level backups spread it over more factories. Which one reflects
Acme's real contracts is a client decision; both are one setting.

## 7. What-if scenarios

All scenarios work on a copy of one run's plan.

| Scenario | Output |
|---|---|
| Hold a customer | Units removed per lot and size, NSV at risk, new lot quantity |
| Check minimums (MOQ cascade) | Lots that fall below MOQ after a hold, with a suggested same-market fix. A fix never uses the held customer's own demand, reserves each requisition so no two lots claim it, and is re-checked for MOQ, MPQ (per article per factory) and factory load |
| Delay production | Shift a factory's production by N days: new arrival dates, late lots, late units, affected customers and NSV at risk |
| Switch factories | Certification check, cost-multiplier and lead-time deltas, new arrival date, MOQ status. Capacity is recalculated on a copy of the ledger with the lot removed from its factory and added to the target (load before and after at both), and MPQ is re-checked at both factories |

### Manual decisions (Go/No-Go)

The spec requires the tool to distinguish automatic rules from manual overrides. The engine's plan is never
changed; planner decisions are saved separately (`outputs/overrides.json`) and applied on top:

| Override | Effect |
|---|---|
| Lot decision: Buy / No-Go / Delay | No-Go and Delay lots are left out of the exported buy plan; Buy on a review lot approves it |
| Factory switch (certified factories only) | Cost, lead time, arrival and the target factory's load recalculated; a warning if the target is above the threshold |
| Customer hold (applied from the what-if tab) | That customer's units removed from every lot; a lot with nothing left becomes No-Go; lots falling below MOQ get a warning |

Every changed lot is marked `decision_type = manual` with a note explaining the change, KPIs show the change
against the automatic plan, and a week can be reverted to the automatic plan in one click.

## 8. Pull-forward analysis (spec 3.3)

For a run, the engine projects each factory's weekly load over the current and next four buying windows: the run's
ledger plus open demand placed at its primary factory. Each window's load is reported as its average (units over
capacity × weeks, using exactly the same weeks for both) and its **busiest week**. A window is flagged when its
busiest week reaches 85%, because an average can hide one overloaded week.

For each flagged window, open demand is moved one article-market group at a time, largest first, into the closest
earlier window that can take it. Each move is tested on a working copy of the ledger that already holds the moves
accepted before it, so recommendations never claim the same capacity. A move is accepted only if every affected week
and the target window's busiest week stay below 85%, the market still reaches MOQ, the article reaches MPQ at the
factory in the target window, and what stays behind is zero or still reaches MPQ. Moves stop once the window is
back below 85%. Each recommendation reports units and the busiest week before and after, in both windows, plus the
cost of the alternative (routing to the backup in the overloaded window).

## 8b. Demand and load forecast (`engine/forecast.py`)

At a given run the plan only knows the requisitions received so far, but requisitions keep arriving every week and
reach production about three months later. The forecast estimates that unseen demand and the factory load it brings.

- **Target**: plannable units arriving per MRP week at each primary factory (wholesale demand without an order is
  excluded, as Rule 5 moves it to Future), 1-17 weeks ahead.
- **No look-ahead**: every feature and model uses only weeks up to the run; a test scrambles all later weeks and
  checks that nothing changes. Actuals from later weeks are shown in the app for comparison only.
- **Signal**: demand follows the buying stage in the MRP calendar, which is scheduled in advance: fall/winter V1 is
  about a tenth of V2/V3, spring/summer is flatter. Features are the stage (season type, range version, weeks into
  the stage), the same stage in earlier seasons, the same week last year, recent level, horizon and factory.
- **Model selection by walk-forward backtest** (30 forecast dates from week 40, 17 weeks ahead each):

| Model | WAPE, all horizons |
|---|---|
| Stage-seasonal (same buying stage in earlier seasons) | **29.9%** (in use) |
| Extra Trees, learning a correction to the stage baseline | 32.5% |
| Same week last year | 33.6% |
| Gradient boosting | 34.2% |
| 4-week moving average | 79.6% |

  With two years of data each buying stage has occurred at most twice, so the learned models cannot yet beat the
  stage baseline; Extra Trees stays as the challenger (`forecast.model`) and is re-evaluated as data grows.
- **Range**: P10-P90 from the model's own past forecast errors per horizon band, using only errors known at the run.
  In the backtest 79% of actuals fall inside the 80% range.
- **Load**: forecast units are released with the arrival-to-release lags observed so far, bought at the buying
  window of the release date, produced from that window's PO date over the factory's article-master manufacturing
  time (the client's planning default for demand that does not exist yet), spread by business days. The result is
  unconstrained (at the primary factory, before backup routing), shown next to committed and known open load.
- **Early warning**: a window whose busiest week is below 85% on known demand but at or above 85% with the forecast.
- **Limits**: before a full year of history (about week 53) some future stages have no earlier season; the forecast
  then falls back to the recent level, and the app says so.

## 9. Validation (agreed success criteria)

| Check | Result |
|---|---|
| Valid recommendations: certified factory, single article and market, MOQ met or warned, grouping window respected | 0 violations |
| Complete accounting: every requisition has one outcome, no requisition in two lots, units add up | Passed (25,141 requisitions, 17,554,643 units) |
| Monthly buying: purchases committed only in buying runs | Passed (23 buying runs) |
| Capacity: no factory week above the limit except labelled last-chance lots | Passed |
| Correct scenarios: hand-calculated checks | Passed (tests/test_scenarios.py); worked examples in `docs/worked_examples.md` |
| Comparison with a reference plan | See below |

Tests: `pytest` runs rule unit tests, integration tests on the full plan, scenario hand checks,
manual-decision tests, data checks and API tests. The former Streamlit-only screen tests have been removed;
the remaining suite needs a fresh run after this change. These tests include checks for internal review
finding: purchases only in buying runs, the 84% + 500-unit capacity case, held customers never used in a fix and no
requisition reused, factory-switch load after the move, and pull-forward averages and combined moves.

`docs/worked_examples.md` walks through real lots step by step (purchase window, grouping, MOQ/MPQ, capacity
routing, piggyback, wholesale exclusion, customer hold, delay, factory switch, accounting). The script that
writes it re-checks every number against the engine.

### Comparison with the as-is reference

The as-is reference uses the factory assignments in the supplied data and buys every requisition in the run it
appears, with no rules. The agreed reference plan is still to be confirmed with the client.

| Metric (all 100 runs) | Our plan | As-is |
|---|---|---|
| Units bought | 7.11M | 17.55M |
| Production cost | $652M | $1.773B |
| Cost per unit | $91.62 | $100.98 |
| On-time share of units bought | 83.2% | 98.0% |
| Routed to backup | 15% of lots | 56% of requisitions |
| Unresolved units (shown separately) | 0.55M | n/a (no rules applied) |
| Units needing planner review (no capacity) | 4.55M | n/a (capacity not checked) |

The as-is plan buys everything immediately, ignores MOQ (3,179 article-market lots below 300), the wholesale
exclusion rule and factory capacity, so its volumes are not comparable one to one.

Two effects of the changes are worth discussing with the client:

- **Monthly buying lowers the on-time share** (83.2%, against 98.0% for the as-is plan, which buys every week). All late lots are late
  starts: demand that arrives between two windows with an order-by date before the next window can only be
  ordered once that date has passed. Allowing urgent demand to be bought in a weekly run would recover most of this.
- **Respecting capacity moves 4.6M units to planner review.** Demand exceeds what the factories can make at 100%;
  these lots need a decision (extra capacity, a third certified factory, a later date, or No-Go).

### Evaluation against the client's baseline

The client named the factory assignments recorded in `fact_purchase_requisitions` as the baseline, evaluated on the
same requisitions and units that our plan buys. The baseline places each at its supplied factory with its own lead
times, starting on the PO date of the run it appeared in (`engine/metrics.py: baseline_evaluation`).

| Measure (same 8,324 requisitions) | Baseline | Our plan |
|---|---|---|
| Backup-triggered assignments | 54.8% | 10.8% |
| Load spread across factories (average weekly standard deviation) | 68.5 pts | 24.4 pts |
| Busiest factory each week (average) | 190.2% | 82.5% |
| Factory-weeks above 100% | 67 | 0 |
| Article-market lots below MOQ 300 | 21.9% | 11.2% |
| Production cost | $610M | $583M |
| Units on time | 97.0% | 75.0% |

Our plan reduces backup-triggered assignments, lowers utilisation variance and protects MOQ per market, at lower
cost and never above the 100% ceiling. Its on-time share is lower because production starts on the buying window's
PO date and demand that arrives between windows can start after its release date.

**Retried demand.** Demand sent to planner review or left unresolved stays in the open pool and is retried in later
windows, so it stays visible. Once its release date has passed it could only arrive late, so it is no longer bought
automatically: it stays in planner review, marked as late (`capacity.retried_late_demand: planner_review`; `buy`
restores automatic late purchases). With automatic late purchases the on-time share was 40.7%: those lots arrived a
median 45 days late, and the client asked for such conflicts to be surfaced for the planner rather than resolved
automatically.

## 10. Deviations and assumptions

| Topic | Choice | Why |
|---|---|---|
| Order of rules | Capacity routing runs after grouping | Routing needs lot quantities; certification is still enforced on every assignment |
| Buying window | Monthly; the PO day on days 15-21 | Client decision (third week); exact days are our reading, configurable |
| Weeks between windows | Draft of the next window, nothing committed | Planners see the purchase build up; confirm |
| Capacity source | Rolling ledger, units spread over manufacturing weeks | Client decision; the static table exceeds 100% in 336 weeks |
| Backup routing | Factory-level chain to CN04 (data v5) | Every supplied v5 backup assignment follows it; article-level is one setting away |
| Capacity check | Load including the lot; factory limit 100% | Spec 3.2; the limit is configurable (overtime?) |
| No certified factory has room | Planner review, not bought | A warning does not create capacity; last-chance lots keep warn-don't-block |
| Lots below MOQ/MPQ | Wait for the next window if production can still start on time | Avoids declaring demand unresolved too early; configurable |
| Last chance | Includes forecast-only demand; bought below minimums with a warning | Catalogue closure; client said warn, don't block |
| Piggyback | Whole requisitions, same market only | Keeps accounting exact and respects per-market MOQ |
| MPQ scope | Per article per factory per buying window | Spec: factory level across markets in the same window |
| Suggested RDD | Earliest RDD in the lot, or the expected arrival if later | Gives the planner a realistic date |
| Lead time at another factory | Midpoint of that factory's range | No per-requisition lead time exists for factories other than the supplied one |

## 11. Open questions for the client

1. Backup routing: data v5 follows the factory chain to CN04; article-level backups buy 0.5M more units. Which matches Acme's contracts?
2. Rule 2: anchor on the earliest RDD, or allow chaining?
3. When no certified factory has room: planner review (current), third certified factory, delay, or buy with a warning?
   Is 100% a hard limit, or is overtime possible?
4. Is "third week" days 15-21? Are weekly drafts useful, and should urgent demand be bought between windows?
5. The reference plan and the weighting of cost, on-time units and unresolved demand.
6. Delivery history or permission to use public delay data (planned extension).
