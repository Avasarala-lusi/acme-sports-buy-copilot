# Acme Sports Network Buy Copilot

Team Vantage (University at Buffalo) × Globant. A weekly buy-planning engine and web app for the Acme Sports supply-chain challenge.

## What it does
- **Spec rule engine:** applies the 6 buy-plan rules, factory certification and capacity, and writes `fact_buy_plan_suggestions` with a reason per lot.
- **What-if simulator:** customer hold, MOQ cascade, delay and factory swap.
- **Load forecast:** Extra Trees + seasonal ensemble, 4 buying windows ahead.
- **Network optimizer:** MILP (OR-Tools) across all six factories, robust to Monte Carlo delay scenarios.
- **RL threshold tuning** and a **plain-English question layer** (bonus).

## Layout
| Folder | Contents |
|---|---|
| `config/` | `thresholds.yaml`: every threshold and client decision |
| `engine/` | data loader, rules, capacity ledger, optimizer |
| `sim/` | what-if scenarios, Monte Carlo, RL environment |
| `api/` | FastAPI service for the web front end |
| `notebooks/` | trend analysis (5 required analyses) |
| `tests/` | pytest suite |
| `data/raw/` | client CSVs, **local only, not committed** |

## Setup
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```
Put the nine ACME CSVs in `data/raw/`, then run:
```bash
pytest
```

## Team
Akshay Revankar · Lusi Zhang · Dilip Nallamasa
