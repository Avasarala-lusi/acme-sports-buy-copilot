# Acme Sports Buy Planner

Team Vantage (University at Buffalo) × Globant. A weekly buy-planning engine and app for the Acme Sports
supply-chain challenge.

## Phase 1 (scoping review scope): done
- **Rule engine:** the six buy-plan rules, factory certification and capacity, with a reason for every lot.
  Writes `fact_buy_plan_suggestions` for all 100 MRP runs.
- **Planner app:** select a week → generate the plan → test a change → export (CSV and Excel).
- **What-if scenarios:** hold a customer, check minimums, delay production, switch factories.
- **Pull-forward analysis:** capacity-driven, across the next four buying windows, with per-market MOQ checks.
- **Trend notebook:** the five required analyses over 100 weeks.
- **Validation:** complete accounting, rule-violation checks, hand-checked scenarios, comparison with the as-is plan.
- **Technical documentation:** `docs/technical_documentation.md`.

## Phase 2: next
Load forecast, network optimiser across all six factories, delay-risk simulation, RL threshold tuning, custom front end.

## Run it
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```
Put the nine ACME CSVs in `data/raw/` (client data is never committed), then:
```bash
python scripts/run_plan.py                 # plan all runs, write outputs/
streamlit run app/streamlit_app.py         # planner app
uvicorn api.main:app --reload              # REST API
python notebooks/build_trend_notebook.py   # rebuild the trend notebook
pytest                                     # 41 tests
```

## Layout
| Folder | Contents |
|---|---|
| `config/` | `thresholds.yaml`: every threshold and client decision |
| `engine/` | data loader, rules, capacity ledger, planner, accounting, metrics, pull-forward, outputs |
| `sim/` | what-if scenarios |
| `app/` | Streamlit planner app |
| `api/` | FastAPI service |
| `notebooks/` | trend analysis notebook and its builder |
| `scripts/` | command-line runner |
| `tests/` | pytest suite |
| `docs/` | technical documentation |
| `data/raw/`, `outputs/` | local only, not committed |

## Team
Akshay Revankar · Lusi Zhang · Dilip Nallamasa
