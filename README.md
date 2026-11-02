# Acme Sports Buy Planner

Team Vantage (University at Buffalo) × Globant. A buy-planning engine and app for the Acme Sports
supply-chain challenge: weekly visibility, MID/EOM purchases. Runs on the client's data v5.

## Current capabilities
- **Rule engine:** the six buy-plan rules, factory certification and capacity, with a reason for every lot.
  Purchases are committed in configured MID/EOM buying runs; intervening weeks preview the next window.
  Capacity is checked with each new lot included, and lots that fit no certified factory go to planner review.
  Under the provisional calendar there are 46 buying runs in the 100 MRP runs.
  Exact cutoff-to-PO dates remain configurable assumptions, not a newly confirmed client calendar.
- **Web app** (`frontend/`): buy plan with rule explanations and Go/No-Go decisions, what-if scenarios, pull-forward, capacity, demand and load forecast, factory network map, export and data checks.
- **What-if scenarios:** hold a customer, check minimums, delay production, switch factories.
- **Go/No-Go decisions:** saved changes replay later demand and capacity. Hold/Delay applies to one window;
  No-Go cancels selected PRs. Approvals and last-chance status never bypass the 100% ceiling.
- **Pull-forward analysis:** capacity-driven, across the next four buying windows; moves are tested together on one ledger with MOQ and MPQ checks.
- **Demand and load forecast:** 17-week intake estimates with explicit fallback/range status; saved-decision load and four-window pressure warnings beside purchase decisions. Eight methods run under past-only tests with a separate final period. Forecasts do not create purchases or reserve capacity.
- **Planning impact:** simulated late and unbought demand by market, product line, article, factory and customer. $21/unit is illustrative exposure, not a verified price, penalty or profit loss.
- **Trend notebook** (`notebooks/trend_analysis.ipynb`): the five required analyses over 100 weeks: seasonal demand, factory utilisation and backup triggers, pull-forward opportunities, forecast vs confirmed-order coverage, and sales value by market and credit rating.
- **Validation:** complete accounting, rule-violation checks, hand-checked scenarios, comparison with the as-is plan and evaluation against the client's baseline.
- **Documentation:** `docs/technical_documentation.md`; hand-checkable calculations in `docs/worked_examples.md`;
  planning terms in `docs/glossary.md`; capacity review checklist in `docs/capacity_validation_checklist.md`.

## Roadmap

Current rule details and provisional defaults: `docs/client_rule_updates.md`. Old worked examples and
numeric comparisons must be regenerated before reuse. `suggested_rdd` is the single proposed arrival date.

Optimizer, simulated on-time risk, planner benchmark, disruption drill and data-health extensions are
**upcoming prototypes**, disabled in this release (`features.experimental: false`). Their code is retained
for later weeks; it is not validated core functionality. See [current release contract](docs/core_forecast_release.md).

## Run it
Validated with Python 3.12; use Python 3.12 and Node.js 18+ for the documented setup.
```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
(cd frontend && npm install && npm run build)  # build the web app (not committed; rebuild after every pull)
```
Put the nine ACME CSVs from data v5 in `data/raw/` (client data is never committed), then:
```bash
uvicorn api.main:app --port 8000           # API and the built web app: open http://localhost:8000/ui
```
Other commands:
```bash
python scripts/run_plan.py                 # plan all runs, write outputs/
(cd frontend && npm run dev)               # web app with live reload, http://localhost:5173 (API must be running)
jupyter notebook notebooks/trend_analysis.ipynb  # the five trend analyses
python scripts/build_worked_examples.py     # regenerate the worked examples
pytest -m "not experimental"               # current core planning + forecast checks
pytest -m experimental                     # optional prototypes; not current acceptance
```
The first load processes all 100 runs and may take a while; the automatic plan is cached in `outputs/`
and rebuilt when engine code, configuration or input data changes. Saved decisions use a separate
replay and never alter the cached automatic reference.

On macOS, XGBoost also requires the OpenMP runtime (`brew install libomp`). Windows users can create
the environment with `py -3.12 -m venv .venv` and activate `.venv\\Scripts\\activate` in Command Prompt
or `.venv\\Scripts\\Activate.ps1` in PowerShell. Run `python -m pip check` after installing dependencies.
The Forecast page's method selector changes the preview only; decision warnings use `forecast.model`.

## Updating to the latest version
```bash
git checkout main && git pull
pip install -r requirements.txt
(cd frontend && npm install && npm run build)  # without this, /ui keeps showing the previous build
```
Then restart `uvicorn` and hard-refresh the browser (Cmd+Shift+R on macOS, Ctrl+Shift+R on Windows).
Check that `data/raw/` holds data v5 (25,141 requisitions in `fact_purchase_requisitions.csv`).
`git log -1 --oneline` shows the version you are on; compare it with the latest commit on GitHub.

## Troubleshooting
| Symptom | Fix |
|---|---|
| The web app looks out of date | Rebuild it (`npm run build` in `frontend/`), restart `uvicorn`, hard-refresh |
| `/ui` shows "Not Found" | The web app has not been built yet: run `npm install && npm run build` in `frontend/` |
| Numbers differ between teammates | Different data versions: everyone needs data v5 in `data/raw/` |
| Port 8000 already in use | Another copy is running: stop it, or start on another port (`--port 8001`) |

## Layout
| Folder | Contents |
|---|---|
| `config/` | `thresholds.yaml`: every threshold and client decision |
| `engine/` | data loader, rules, capacity ledger, planner, accounting, metrics, pull-forward, outputs |
| `sim/` | what-if scenarios |
| `api/` | FastAPI service |
| `frontend/` | React web app (see frontend/README.md) |
| `notebooks/` | trend analysis notebook (five analyses) |
| `scripts/` | command-line runner and worked-examples generator |
| `tests/` | pytest suite |
| `docs/` | technical documentation, worked examples, glossary, capacity checklist |
| `data/raw/`, `outputs/` | local only, not committed |

## Team
Akshay Revankar · Lusi Zhang · Dilip Nallamasa
