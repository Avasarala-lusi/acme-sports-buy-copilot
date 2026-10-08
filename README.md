# Acme Sports Buy Planner

Team Vantage (University at Buffalo) × Globant. A weekly buy-planning engine and app for the Acme Sports
supply-chain challenge.

## Current capabilities
- **Rule engine:** the six buy-plan rules, factory certification and capacity, with a reason for every lot.
  Writes `fact_buy_plan_suggestions` for all 100 MRP runs.
- **Web app** (`frontend/`): buy plan with rule explanations and Go/No-Go decisions, what-if scenarios, pull-forward, capacity, export and data checks.
- **Streamlit app** (`app/`): the same workflow in a lightweight analyst interface.
- **What-if scenarios:** hold a customer, check minimums, delay production, switch factories.
- **Go/No-Go decisions:** Buy / No-Go / Delay, factory switches and customer holds saved as manual changes, reversible.
- **Pull-forward analysis:** capacity-driven, across the next four buying windows, with per-market MOQ checks.
- **Trend notebook:** the five required analyses over 100 weeks.
- **Validation:** complete accounting, rule-violation checks, hand-checked scenarios, comparison with the as-is plan.
- **Technical documentation:** `docs/technical_documentation.md`; hand-checkable calculations in `docs/worked_examples.md`.

## Roadmap
Load forecast, network optimiser across all six factories, delay-risk simulation, RL threshold tuning, custom front end.

## Run it
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```
Put the nine ACME CSVs in `data/raw/` (client data is never committed), then:
```bash
python scripts/run_plan.py                 # plan all runs, write outputs/
uvicorn api.main:app --port 8000           # API (also serves the built web app at /ui)
(cd frontend && npm install && npm run dev) # web app in development, http://localhost:5173
streamlit run app/streamlit_app.py         # analyst app
python notebooks/build_trend_notebook.py   # generate a fresh trend notebook (trend_analysis_generated.ipynb)
python scripts/build_worked_examples.py     # regenerate the worked examples
pytest                                     # 58 tests
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
| `notebooks/` | trend analysis notebook and its builder |
| `scripts/` | command-line runner |
| `tests/` | pytest suite |
| `docs/` | technical documentation |
| `data/raw/`, `outputs/` | local only, not committed |

## Team
Akshay Revankar · Lusi Zhang · Dilip Nallamasa
