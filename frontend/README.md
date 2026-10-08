# Buy Planner web app

React + TypeScript front end for the planning API (`api/main.py`).

## Run in development
Start the API from the project root, then the web app:
```bash
uvicorn api.main:app --port 8000
```
```bash
cd frontend && npm install && npm run dev
```
Open http://localhost:5173. Calls to `/api/*` are proxied to the API on port 8000
(override with `API_PROXY_TARGET` in `frontend/.env`).

## Build and serve with the API
```bash
cd frontend && npm run build
```
The API serves the built app at http://localhost:8000/ui (the root URL redirects there).

## Structure
| Path | Contents |
|---|---|
| `src/api/types.ts` | Response shapes returned by the API |
| `src/api/client.ts` | One function per API endpoint |
| `src/components/` | Layout, table, drawer and shared UI elements |
| `src/pages/` | Buy plan, Test a change, Pull-forward, Capacity, Export, Data & checks, Planned capabilities |
| `src/lib/` | Formatting helpers and the selected-run state |

Planned capabilities are switched on through the API's `/features` endpoint as they are delivered.
