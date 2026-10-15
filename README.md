# Acme Sports Buy Planner

Team Vantage (University at Buffalo) × Globant. A buy-planning engine and app for the Acme Sports
supply-chain challenge: weekly drafts, monthly purchases. Runs on the client's data v5.

## Current capabilities
- **Rule engine:** the six buy-plan rules, factory certification and capacity, with a reason for every lot.
  Purchases are committed once a month in the buying window; the weeks in between show a draft of it.
  Capacity is checked with each new lot included, and lots that fit no certified factory go to planner review.
  Writes `fact_buy_plan_suggestions` for all 23 buying windows in the 100 MRP runs.
- **Web app** (`frontend/`): buy plan with rule explanations and Go/No-Go decisions, what-if scenarios, pull-forward, capacity, factory network map, export and data checks.
- **Streamlit app** (`app/`): the same workflow in a lightweight analyst interface.
- **What-if scenarios:** hold a customer, check minimums, delay production, switch factories.
- **Go/No-Go decisions:** Buy / No-Go / Delay, factory switches and customer holds saved as manual changes, reversible.
- **Pull-forward analysis:** capacity-driven, across the next four buying windows; moves are tested together on one ledger with MOQ and MPQ checks.
- **Trend notebook** (`notebooks/trend_analysis.ipynb`): the five required analyses over 100 weeks: seasonal demand, factory utilisation and backup triggers, pull-forward opportunities, forecast vs confirmed-order coverage, and sales value by market and credit rating.
- **Validation:** complete accounting, rule-violation checks, hand-checked scenarios, comparison with the as-is plan.
- **Documentation:** `docs/technical_documentation.md`; hand-checkable calculations in `docs/worked_examples.md`;
  planning terms in `docs/glossary.md`; capacity review checklist in `docs/capacity_validation_checklist.md`.

## Roadmap
Data health checks, load forecast, on-time probability, network optimiser with a cost-vs-service slider, planner
benchmark and disruption drill; stretch: learned thresholds and plain-English questions.

## Run it
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```
Put the nine ACME CSVs from data v5 in `data/raw/` (client data is never committed), then:
```bash
python scripts/run_plan.py                 # plan all runs, write outputs/
uvicorn api.main:app --port 8000           # API (also serves the built web app at /ui)
(cd frontend && npm install && npm run dev) # web app in development, http://localhost:5173
streamlit run app/streamlit_app.py         # analyst app
jupyter notebook notebooks/trend_analysis.ipynb  # the five trend analyses
python scripts/build_worked_examples.py     # regenerate the worked examples
pytest                                     # 91 tests
```

## Layout
| Folder | Contents |
|---|---|
| `config/` | `thresholds.yaml`: every threshold and client decision |
| `engine/` | data loader, rules, capacity ledger, planner, accounting, metrics, pull-forward, outputs |
| `sim/` | what-if scenarios |
| `app/` | Streamlit planner app |
| `api/` | FastAPI service |
| `frontend/` | React web app (see frontend/README.md) |
| `notebooks/` | trend analysis notebook (five analyses) |
| `scripts/` | command-line runner and worked-examples generator |
| `tests/` | pytest suite |
| `docs/` | technical documentation, worked examples, glossary, capacity checklist |
| `data/raw/`, `outputs/` | local only, not committed |

## Team
Akshay Revankar · Lusi Zhang · Dilip Nallamasa
