"""
JEVelric Dashboard API — FastAPI backend.

Reads cases/*.json and data/case_pack.csv from the repo root.
Serves the public site and dashboard as static files.
All GET endpoints are functional; POST/future endpoints return 501.
"""
from __future__ import annotations

import csv
import asyncio
import json
import os
import re
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
API_DIR = Path(__file__).resolve().parent                    # web/dashboard/api/
DASHBOARD_DIR = API_DIR.parent                               # web/dashboard/
WEB_DIR = DASHBOARD_DIR.parent                               # web/
REPO_ROOT = WEB_DIR.parent                                   # repo root
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CASES_DIR = Path(os.environ.get("CASES_DIR", str(REPO_ROOT / "cases")))
CASE_PACK_CSV = Path(os.environ.get("CASE_PACK_CSV", str(REPO_ROOT / "data" / "case_pack.csv")))
RUNS_DIR = REPO_ROOT / "reports" / "console_runs"
MAX_UPLOAD_BYTES = 1_000_000
MAX_RUN_CASES = 50
REQUIRED_CASE_COLUMNS = {"case_id", "trigger_type", "trigger_text", "flagged_txn_id", "card_id", "customer_id"}
RUNS: dict[str, dict[str, Any]] = {}
RUNS_LOCK = threading.Lock()
RUN_GATE = threading.Lock()

# ---------------------------------------------------------------------------
# Load case_pack.csv once at startup for trigger enrichment
# ---------------------------------------------------------------------------
_trigger_lookup: dict[str, dict[str, Any]] = {}


def _load_trigger_data() -> None:
    """Parse case_pack.csv into a lookup dict keyed by case_id."""
    if not CASE_PACK_CSV.exists():
        return
    with open(CASE_PACK_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cid = row.get("case_id", "").strip()
            if cid:
                _trigger_lookup[cid] = {
                    "trigger_type": row.get("trigger_type", "").strip(),
                    "trigger_text": row.get("trigger_text", "").strip(),
                    "flagged_txn_id": row.get("flagged_txn_id", "").strip(),
                    "card_id": row.get("card_id", "").strip(),
                    "customer_id": row.get("customer_id", "").strip(),
                    "risk_score": row.get("risk_score", "").strip() or None,
                    "opened_at": row.get("opened_at", "").strip(),
                }


_load_trigger_data()

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="JEVelric Dashboard API",
    description="Read-only API serving the 20 HHGOA fraud investigation cases.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_case(case_id: str) -> dict[str, Any]:
    """Read a single case JSON file and return its parsed contents."""
    path = CASES_DIR / f"{case_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _all_case_ids() -> list[str]:
    """Return sorted list of case IDs from the cases directory."""
    if not CASES_DIR.exists():
        return []
    return sorted(
        p.stem for p in CASES_DIR.glob("*.json")
    )


def _is_changed(data: dict[str, Any]) -> bool:
    """Determine if the agent changed its recommendation during investigation."""
    nba = data.get("next_best_actions", {})
    what_changed = nba.get("what_changed", "nothing")
    if what_changed and what_changed.lower() != "nothing":
        return True
    # Also compare initial vs final action lists as a fallback
    initial = nba.get("initial", [])
    final = nba.get("final", [])
    if len(initial) != len(final):
        return True
    initial_actions = {a.get("action") for a in initial}
    final_actions = {a.get("action") for a in final}
    return initial_actions != final_actions


# ---------------------------------------------------------------------------
# GET endpoints — fully implemented
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    """Report API and TigerGraph configuration without claiming live connectivity."""
    from src import config
    return {
        "status": "ok",
        "graph_configured": config.tigergraph_configured(),
        "graph_name": config.TG_GRAPH_NAME,
        "transaction_count": None,
    }


@app.get("/api/cases")
async def list_cases():
    """List all 20 cases with summary fields for the case table."""
    case_ids = _all_case_ids()
    summaries = []
    for cid in case_ids:
        try:
            data = _read_case(cid)
        except HTTPException:
            continue
        case_obj = data.get("case", {})
        sar_obj = data.get("sar", {})
        trigger_info = _trigger_lookup.get(cid, {})
        summaries.append({
            "case_id": cid,
            "verdict": case_obj.get("verdict", ""),
            "pattern": case_obj.get("pattern", ""),
            "status": case_obj.get("status", ""),
            "fraud_probability": case_obj.get("fraud_probability", 0),
            "exposure_usd": case_obj.get("exposure_usd", 0),
            "changed": _is_changed(data),
            "sar_filed": sar_obj.get("file", False),
            "trigger_type": trigger_info.get("trigger_type", ""),
            "evidence_count": len(case_obj.get("evidence", [])),
            "tool_calls": data.get("tool_calls", 0),
            "latency_s": data.get("latency_s", 0),
        })
    return {"cases": summaries, "total": len(summaries)}


@app.get("/api/case-pack")
async def download_case_pack():
    if not CASE_PACK_CSV.is_file():
        raise HTTPException(status_code=404, detail="Configured case_pack.csv was not found")
    return FileResponse(CASE_PACK_CSV, filename="case_pack.csv", media_type="text/csv")


@app.get("/api/cases/{case_id}")
async def get_case(case_id: str):
    """Full Answer JSON for one case, enriched with trigger info from case_pack.csv."""
    data = _read_case(case_id)
    # Enrich with trigger info without modifying the source file
    trigger_info = _trigger_lookup.get(case_id, {})
    if trigger_info:
        data["trigger_type"] = trigger_info.get("trigger_type", "")
        data["trigger_text"] = trigger_info.get("trigger_text", "")
        data["flagged_txn_id"] = trigger_info.get("flagged_txn_id", "")
        data["card_id"] = trigger_info.get("card_id", "")
        data["customer_id"] = trigger_info.get("customer_id", "")
        data["risk_score"] = trigger_info.get("risk_score")
        data["opened_at"] = trigger_info.get("opened_at", "")
    return data


@app.get("/api/config")
async def get_config():
    """Expose non-secret runtime settings to the console."""
    from src import config, llm
    return {
        "graphrag_mode": config.GRAPHRAG_MODE,
        "llm_providers": llm.llm_provider_order(),
        "jev_enabled": config.JEV_ENABLED,
        "graph_name": config.TG_GRAPH_NAME,
    }


# ---------------------------------------------------------------------------
# POST / future endpoints — 501 stubs
# ---------------------------------------------------------------------------

@app.post("/api/investigations/run")
async def run_investigation(file: UploadFile = File(...), graphrag_mode: str = Form("static")):
    """Validate an uploaded case pack and start the live case runner."""
    return await _start_live_run(file, graphrag_mode)


@app.get("/api/investigations/{run_id}/stream")
async def stream_investigation(run_id: str):
    """Stream case-by-case LangGraph progress using server-sent events."""
    return await _stream_live_run(run_id)
    """Stream investigation progress via SSE.

    Future: returns Server-Sent Events streaming state-machine progress
    node by node (graph_retrieval -> jev_assess -> stop_check -> ...) as
    it happens, for a 'watch it think' demo view.
    """
    return JSONResponse(
        status_code=501,
        content={
            "detail": "Real-time investigation streaming is not yet implemented. "
                      "This endpoint will provide SSE events for each orchestration "
                      "state transition during a live investigation run.",
        },
    )


async def _start_live_run(file: UploadFile, graphrag_mode: str) -> dict[str, Any]:
    mode = graphrag_mode.strip().lower()
    if mode not in {"static", "grip"}:
        raise HTTPException(status_code=422, detail="graphrag_mode must be 'static' or 'grip'")
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="CSV upload exceeds 1 MB")
    try:
        reader = csv.DictReader(raw.decode("utf-8-sig").splitlines())
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="Upload must be a UTF-8 CSV") from exc
    missing = sorted(REQUIRED_CASE_COLUMNS - set(reader.fieldnames or []))
    if missing:
        raise HTTPException(status_code=422, detail="CSV is missing required columns: " + ", ".join(missing))
    rows = [{str(k): (v or "").strip() for k, v in row.items() if k is not None} for row in reader]
    if not rows:
        raise HTTPException(status_code=422, detail="CSV contains no case rows")
    if len(rows) > MAX_RUN_CASES:
        raise HTTPException(status_code=422, detail=f"Upload may contain at most {MAX_RUN_CASES} cases")
    seen: set[str] = set()
    allowed_triggers = {"risk_score", "customer_report", "analyst_request"}
    for line, row in enumerate(rows, start=2):
        empty = sorted(name for name in REQUIRED_CASE_COLUMNS if not row.get(name))
        if empty:
            raise HTTPException(status_code=422, detail=f"Row {line} has empty required fields: {', '.join(empty)}")
        if row["case_id"] in seen:
            raise HTTPException(status_code=422, detail=f"Duplicate case_id at row {line}: {row['case_id']}")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", row["case_id"]):
            raise HTTPException(status_code=422, detail=f"Row {line} case_id may contain only letters, numbers, '_' and '-'")
        seen.add(row["case_id"])
        if row["trigger_type"] not in allowed_triggers:
            raise HTTPException(status_code=422, detail=f"Row {line} has unsupported trigger_type: {row['trigger_type']}")
        if row["trigger_type"] == "risk_score" and not row.get("risk_score"):
            raise HTTPException(status_code=422, detail=f"Row {line} risk_score is required for a risk_score trigger")
        if row.get("risk_score"):
            try:
                score = float(row["risk_score"])
                if not 0 <= score <= 1:
                    raise ValueError
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"Row {line} risk_score must be between 0 and 1") from exc
    if not RUN_GATE.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Another live investigation run is already in progress")
    run_id = uuid.uuid4().hex
    with RUNS_LOCK:
        RUNS[run_id] = {
            "run_id": run_id, "status": "queued", "total": len(rows), "completed": 0,
            "mode": mode, "events": [], "error": None,
        }
    try:
        threading.Thread(target=_execute_live_run, args=(run_id, rows, mode), daemon=True).start()
    except Exception:
        RUN_GATE.release()
        raise
    return {
        "run_id": run_id, "total": len(rows), "case_ids": [row["case_id"] for row in rows],
        "stream_url": f"/api/investigations/{run_id}/stream",
    }


async def _stream_live_run(run_id: str) -> StreamingResponse:
    with RUNS_LOCK:
        if run_id not in RUNS:
            raise HTTPException(status_code=404, detail="Run not found")

    async def events():
        cursor = 0
        while True:
            with RUNS_LOCK:
                run = RUNS.get(run_id)
                if run is None:
                    return
                batch = run["events"][cursor:]
                cursor += len(batch)
                done = run["status"] in {"completed", "failed"}
            for event in batch:
                yield "data: " + json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n\n"
            if done and not batch:
                break
            if not batch:
                yield ": keep-alive\n\n"
                await asyncio.sleep(0.4)

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })


def _publish(run_id: str, event: dict[str, Any]) -> None:
    with RUNS_LOCK:
        if run_id in RUNS:
            RUNS[run_id]["events"].append(event)


def _execute_live_run(run_id: str, rows: list[dict[str, str]], mode: str) -> None:
    """Execute uploaded cases serially through the production LangGraph."""
    import time
    from src import config, llm
    from src.orchestrator import build_graph
    from src.state import InvestigationState, TriggerType

    previous = (config.GRAPH_BACKEND, config.GRAPHRAG_MODE, config.ANSWERS_DIR)
    output_dir = RUNS_DIR / run_id
    try:
        with RUNS_LOCK:
            RUNS[run_id]["status"] = "running"
        _publish(run_id, {"type": "run_started", "run_id": run_id, "total": len(rows), "mode": mode})
        config.GRAPH_BACKEND = "tigergraph"
        config.GRAPHRAG_MODE = mode
        config.ANSWERS_DIR = output_dir
        _publish(run_id, {"type": "graph_connecting", "graph": config.TG_GRAPH_NAME})
        client = config.get_mcp_client()
        count_result = client.call_tool("tigergraph__get_vertex_count", {
            "graph_name": config.TG_GRAPH_NAME, "vertex_type": "Transaction",
        })
        transaction_count = int((count_result or {}).get("count", 0))
        if transaction_count <= 0:
            raise RuntimeError(f"TigerGraph returned an empty Transaction count: {count_result}")
        _publish(run_id, {
            "type": "graph_connected", "graph": config.TG_GRAPH_NAME,
            "transaction_count": transaction_count, "mode": mode,
            "providers": llm.llm_provider_order(),
        })
        graph = build_graph()
        output_dir.mkdir(parents=True, exist_ok=True)
        stage_labels = {
            "graph_retrieval": "Querying TigerGraph evidence",
            "graphrag_context": "Assembling policy and case context",
            "jev_assess": "Assessing risk and pattern",
            "stop_check": "Checking evidence sufficiency",
            "policy_initial": "Applying initial R1–R10 actions",
            "evidence_request": "Preparing evidence request",
            "simulate_response": "Applying simulated response",
            "policy_final": "Revising actions after response",
            "sar_decision": "Evaluating SAR policy",
            "case_assembly": "Writing investigation summary",
            "graph_write": "Writing case to TigerGraph",
            "answer_validate": "Validating graph IDs and actions",
            "answer_emit": "Saving case answer",
        }
        for index, row in enumerate(rows, start=1):
            case_id = row["case_id"]
            _publish(run_id, {
                "type": "case_started", "case_id": case_id, "index": index,
                "total": len(rows), "trigger": row["trigger_type"],
            })
            initial = InvestigationState(
                case_id=case_id,
                trigger_type=TriggerType(row["trigger_type"]),
                trigger_text=row["trigger_text"],
                flagged_txn_id=str(row["flagged_txn_id"]),
                card_id=row["card_id"],
                customer_id=row["customer_id"],
                risk_score=float(row["risk_score"]) if row.get("risk_score") else None,
            )
            start = time.monotonic()
            try:
                for update in graph.stream(initial, stream_mode="updates"):
                    if isinstance(update, dict):
                        for node_name in update:
                            _publish(run_id, {
                                "type": "stage", "case_id": case_id, "node": node_name,
                                "label": stage_labels.get(node_name, node_name.replace("_", " ").title()),
                            })
                answer_path = output_dir / f"{case_id}.json"
                if not answer_path.exists():
                    raise RuntimeError("Orchestrator finished without emitting an answer file")
                answer = json.loads(answer_path.read_text(encoding="utf-8"))
                answer["latency_s"] = round(time.monotonic() - start, 2)
                answer_path.write_text(json.dumps(answer, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                display_answer = dict(answer)
                for field in ("trigger_type", "trigger_text", "flagged_txn_id", "card_id", "customer_id", "opened_at", "risk_score"):
                    if row.get(field):
                        display_answer[field] = row[field]
                _publish(run_id, {
                    "type": "case_completed", "case_id": case_id, "index": index,
                    "total": len(rows), "answer": display_answer,
                })
                with RUNS_LOCK:
                    RUNS[run_id]["completed"] = index
            except Exception as exc:
                _publish(run_id, {
                    "type": "case_failed", "case_id": case_id, "index": index,
                    "error": str(exc)[:1200],
                })
                raise
        _publish(run_id, {
            "type": "run_completed", "run_id": run_id, "completed": len(rows),
            "output_dir": str(output_dir.relative_to(REPO_ROOT)),
        })
        with RUNS_LOCK:
            RUNS[run_id]["status"] = "completed"
    except Exception as exc:
        message = str(exc)[:1200]
        _publish(run_id, {"type": "run_failed", "run_id": run_id, "error": message})
        with RUNS_LOCK:
            if run_id in RUNS:
                RUNS[run_id]["status"] = "failed"
                RUNS[run_id]["error"] = message
    finally:
        if config.get_grip_client.cache_info().currsize:
            try:
                config.get_grip_client().close()
            except Exception:
                pass
            config.get_grip_client.cache_clear()
        if config.get_mcp_client.cache_info().currsize:
            try:
                config.get_mcp_client().close()
            except Exception:
                pass
            config.get_mcp_client.cache_clear()
        config.GRAPH_BACKEND, config.GRAPHRAG_MODE, config.ANSWERS_DIR = previous
        RUN_GATE.release()


@app.post("/api/cases/{case_id}/approve")
async def approve_case_action(case_id: str):
    """Human-in-the-loop approval for L1/L2 actions.

    Future: accepts {action, approver, decision: "approved"|"denied"}
    and records the human approval decision for an L1/L2 action.
    Currently, L1/L2 actions are recommendation-only in the JSON output.
    """
    return JSONResponse(
        status_code=501,
        content={
            "detail": "Human-in-the-loop approval is not yet implemented. "
                      "This endpoint will accept approval decisions for L1/L2 "
                      "actions that currently appear as recommendations only.",
        },
    )


# ---------------------------------------------------------------------------
# Static file mounts — dashboard and public site
# ---------------------------------------------------------------------------
# These must be mounted AFTER API routes so /api/* takes priority.

SITE_DIR = WEB_DIR / "site"
if SITE_DIR.exists():
    app.mount("/site", StaticFiles(directory=str(SITE_DIR), html=True), name="site")

if DASHBOARD_DIR.exists():
    app.mount("/dashboard", StaticFiles(directory=str(DASHBOARD_DIR), html=True), name="dashboard")

CONSOLE_DIR = WEB_DIR / "console"
if CONSOLE_DIR.exists():
    app.mount("/console", StaticFiles(directory=str(CONSOLE_DIR), html=True), name="console")
