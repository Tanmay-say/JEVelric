# JEVelric web interfaces

The public project page and existing case archive remain available alongside a separate live investigation console.

| Path | Purpose |
|---|---|
| `/site/` | Public project overview and architecture |
| `/dashboard/` | Existing read-only case archive. Its interface and case-view behavior are preserved. |
| `/console/` | New CSV-driven live runner. Upload a case pack, choose static or GRIP context, watch actual LangGraph node events, and inspect each completed answer. |
| `/api/` | FastAPI service for archive data, case-pack download, run creation, and server-sent progress events. |

## Start locally

Run from the repository root with the project virtual environment. The application needs the main project dependencies to execute the agent and the web API dependencies to accept CSV uploads.

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r web\dashboard\api\requirements.txt
uvicorn web.dashboard.api.main:app --reload --port 8000
```

Open `http://localhost:8000/console/`. The archive remains at `http://localhost:8000/dashboard/` and the public page at `http://localhost:8000/site/`.

## Live console behavior

The console accepts UTF-8 case-pack CSVs with `case_id`, `trigger_type`, `trigger_text`, `flagged_txn_id`, `card_id`, and `customer_id`; `risk_score` and `opened_at` are optional. It allows up to 50 cases per upload and runs one job at a time against the configured TigerGraph graph. Every case ID and transaction/card/customer ID must exist in that graph. Set `TG_HOST`, `TG_SECRET`, and `TG_GRAPHNAME` in the repository `.env` before starting a live run.

The server executes the same `src.orchestrator.build_graph()` pipeline used by the command-line runner. It streams real state-machine node updates over server-sent events. A completed answer includes graph evidence, initial and final policy actions, simulated evidence requests when present, SAR narrative, summary, tool/token counts, and elapsed time. Answers are saved under `reports/console_runs/<run-id>/`; the console does not overwrite the submission files in `cases/`.

The graph write still targets TigerGraph's `InvestigationCase` type. Re-running a case ID updates the graph case key used by the existing agent (`G-<case-id>`), so use unique case IDs when you need separate persistent run records. Evidence requests shown by this demo use the project's simulator and are labeled as simulated; they do not contact real cardholders.

`GET /api/cases` and `GET /api/cases/{case_id}` continue to read the existing answer archive. `GET /api/case-pack` provides the current CSV as a starting template. `POST /api/investigations/run` accepts multipart form fields `file` and `graphrag_mode`; `GET /api/investigations/{run_id}/stream` streams progress and answer events.
