# Current core planning and forecast release

October 30, 2026. This is the current release contract. Older worked examples and numerical tables in the
technical-documentation archive are historical and must not be quoted as current validation results.

## This week's scope

The six-rule Buy Plan engine, weekly visibility, formal MID/EOM purchases, saved planner decisions,
what-if checks, capacity, pull-forward, populated exports, five existing analyses and demand/load forecasting.
The optimizer, simulated delivery probability, disruption drill, network benchmark and extra data-health
prototype are upcoming work. They are retained in source but disabled by `features.experimental: false`.
Their old benchmark numbers are not current acceptance evidence.

## Confirmed rules and implementation choices

- Use received PRs only, in chronological run order. Same PR ID is the same demand.
- Routine eligible demand is processed automatically. Exceptions remain actionable for the planner.
- Formal purchase dates match the client's examples: October 28, November 11, November 25 and December 9,
  2026. The remaining semi-monthly calendar formula is a team default, not confirmation of every date.
- Production starts at the formal PO execution date. Manufacturing duration is calendar time; quantities
  are distributed proportionally over Monday–Friday days in the start-inclusive, completion-exclusive period.
  No public-holiday calendar is assumed.
- Use supplied PR lead times at their supplied factory. At another factory, use the arithmetic midpoint
  of its ranges and mark it estimated. Future demand uses article-master manufacturing defaults and known
  eligible article mix; a factory midpoint is the fallback if article defaults are absent.
- Certification is mandatory. Follow the factory backup chain, skipping uncertified factories. Check load
  including the new lot: prefer primary below 85%, then a chain factory below 85%. If none is below 85%,
  the least-loaded certified chain option may be used up to 100%, with a warning. Never assume overtime.
- Last-chance priority comes first; then earliest release date, earliest original RDD, highest net sales
  value, then order backing. Last chance does not waive capacity or silently resolve confirmation conflicts.
- Market/article MOQ is 300. Article/factory MPQ is 1,200 apparel or 2,400 footwear. The current default
  checks one dated purchase window and an anchored 15-calendar-day RDD band. Broader purchase-order pooling
  remains a policy proposal, not an approved replacement or evidence of optimizer superiority.
- Pull-forward uses only known requests and at most four buying windows. Enforce certification, dates,
  market MOQ, factory MPQ and destination headroom. Preserve the future scheduled source run ID.
- Holds apply to exact customer IDs. Hold/Delay is one-window scope; No-Go cancels until reverted.
  An overdue outstanding exception requires an explicit planner decision. Buy still rechecks the constraints.
- `suggested_rdd` is the proposed arrival date (PO + manufacture + transport). Keep original RDD separately.
  A signed date difference is not a measured storage duration or a holding-cost model.

## Outstanding review and status totals

Every outstanding review, MOQ/MPQ shortfall and last-chance/confirmation conflict has a current-run review
lot. A PR appears once in a run, possibly consolidated with compatible requests, and retains its ID and quantity.
These rows reserve no capacity. Buying or cancelling removes the PR from later backlog. Quantity shortfalls
remain available in the Unresolved status view as well; this is not extra demand.

Search accepts PR ID, article or lot. Purchases contains Buy decisions only; delayed/cancelled lot history has
its own tab. Waiting excludes requests already shown in review. The demand-flow totals partition bought,
review-status, quantity-unresolved, waiting, newly forecast-excluded and cancelled units without double counting.
Formal runs commit; intermediate runs show read-only drafts, not actual PO execution.

## Forecast method and boundaries

Forecast eligible weekly PR intake per primary factory from demand available at the selected origin. Known
future buying-stage metadata is assumed available in advance; actual future demand is not a feature and is
hidden from the operational API/chart. It is used only in the separate retrospective evaluation.

The intake horizon is explicitly 17 weeks. The load chart covers four semi-monthly windows, about eight weeks;
these are different horizons. Forecast intake is projected to hypothetical purchase dates using observed
known-request release lags. A default 13-week lag is an assumption only when a factory has no eligible history.
No projected production can start before the predicted PR intake date or the next available purchase window.
Forecasts create neither actual purchase lots nor capacity reservations.

Load has three distinct components:

1. Saved purchase commitments, including manual decisions.
2. Known open demand pressure, before final routing/approval.
3. Estimated demand that has not arrived yet.

Draft purchase previews remain known-demand pressure, not committed production. The known/forecast portions
may exceed 100% because they show unconstrained pressure; committed purchases must remain within 100%.
The table contains exactly four future windows (the next formal window for a draft, or the window after
the current formal purchase). A production week can touch adjacent windows, so window peaks are not additive.

## Models and uncertainty

The shared live and historical dispatch supports stage average, seasonal naive, four-week moving average,
Extra Trees, Random Forest, XGBoost, histogram gradient boosting, and SARIMAX. Tree models learn a correction
to the stage-average baseline from past-only feature/target examples. SARIMAX is AR(1) with stage regressors;
it is not a fitted 52-week seasonal ARIMA component. The current default remains the pre-existing stage average.
The page selector previews another method; it does not change the configured method used by decision warnings.

Training shortages, fit warnings and fit-failure fallbacks are reported. The selected method's own past
forecast errors produce nominal lower/upper ranges; with fewer than 30 errors, an assumed 60–140% range is
explicitly labelled. The legacy `p50` field is the central point estimate, not a proven median. Summing marginal
lower/upper estimates across factories or time creates scenarios, not a calibrated network probability interval.
Forecast demand is not an observed delivery-probability model.

## Warning at the planner's decision

The Decision panel previews the proposed factory and counts the lot once. A bought lot is first removed from
its current reservation; an unbought lot is removed from its known-open projection before the proposal is added.
Thus a factory switch does not double-count the request. Display affected production weeks with committed,
known-open and central/upper forecast pressure. Known-open or higher-scenario pressure is visible even when
the central forecast remains below the soft threshold.

- Committed load over 100% is a hard-capacity constraint; the forecast cannot waive it.
- Forecast/known-open pressure at 85% is advisory. It does not block an otherwise valid purchase.
- Previewing a warning does not mutate the saved plan. Subsequent saved decisions refresh operational load.
- Lot-row load percentages use the final run snapshot, matching the Decision preview rather than an earlier
  routing step. Reverting the last saved override restores the exact automatic reference plan.

## Historical evaluation

With 100 weeks, use complete 17-week selection horizons at origins 40, 44, 48, 52, 56, 60 and 64.
Reserve weeks 84–100 for the final evaluation, forecasting at week 83. The final outcomes do not determine
selection ranks. Methods share origins, targets and WAPE (sum absolute error / sum actual units).
Report incomplete methods, fallbacks and failures; never rank an incomplete run as the winner.

Measured on local V5 data using the fixed methods:

| Method | Selection WAPE | Final weeks 84–100 WAPE |
|---|---:|---:|
| Stage average (configured default) | 34.80% | 22.52% |
| Gradient boosting (selection winner) | 32.10% | 28.43% |
| XGBoost | 32.82% | 30.57% |
| Random Forest | 35.05% | 28.71% |
| Extra Trees | 36.99% | 28.31% |
| SARIMAX with stage regressors | 45.48% | 25.81% |
| Same week last year | 34.04% | 33.82% |
| Four-week average | 87.81% | 36.56% |

Do not tune again on the final period or call its best method a previously unseen winner. The challenger
selected earlier does not beat the existing default on the final period; keep the default and report this
limitation. Tree challengers use stage fallback on 57.14% of selection rows, and SARIMAX on 21.43%; all methods
run without fallback at the final origin. Final default range coverage is 74.51% per factory/week, below the
nominal 80% target. Forecasts are useful warnings, not guarantees.

Seasonality evidence on eligible intake: lag-52 autocorrelation 0.430 versus a rough white-noise bound 0.196;
Kruskal–Wallis stage p about 6.76e-17 and month p about 7.65e-15. Stage means differ about 11.84-fold. These are
exploratory signals with dependence/confounding limitations. Fewer than two full annual cycles limit annual
claims; STL strength about 0.997 can overfit such short history and is indicative only.

## Baseline and dollar reporting

Use supplied assigned factories as the baseline and rebuild loads using the same production accounting.
Report same-demand denominators and disclose different purchase-timing assumptions. The impact page is an
automatic-plan historical comparison, not a live manual scenario or observed delivery performance.
Separate on-time purchases, late purchases and unbought demand. Show unconfirmed last-chance conflicts explicitly;
they are not confirmed lost sales. Factory drilldown uses actual planned factories for purchases and intended
primaries for unbought demand. Roberto's $21/unit is illustrative exposure with $19–22 sensitivity, not a verified
unit price, contractual penalty or profit loss. Production cost remains separate. Do not claim profit neutrality.

## Reproducible setup and checks

Use Python 3.12, the nine local V5 CSVs and `requirements.txt`. macOS XGBoost requires `brew install libomp`.
No container or cloud data upload is required. See README for Windows activation and app build commands.

```bash
python -m pip install -r requirements.txt
python -m pip check
python -m pytest -m "not experimental"
```

Build the frontend with `npm run build`, restart the backend and refresh the browser. Engine/config/data changes
invalidate caches; manual-decision changes invalidate operational load without retraining historical intake.
Raw data and real saved decisions are not changed by the test suite; API tests use temporary decision stores.
The release-validation result and any remaining limitations are recorded in the project decision log.

Validation on October 30: the core suite completed with **144 passed and 7 experimental tests deselected**.
After the final display and empty-override replay corrections, focused API/impact tests completed with
37 passed, and review/client-rule/forecast tests with 41 passed. Production frontend builds passed.
One existing Starlette/httpx deprecation warning remains. This is local release-candidate validation,
not client acceptance or proof of perfect forecast accuracy.
