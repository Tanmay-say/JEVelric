"""
Entrypoint. Reads data/case_pack.csv, runs each case through the compiled
LangGraph orchestrator (src/orchestrator.py), writes cases/<case_id>.json.

Usage:
    python -m src.main                 # all 20 cases
    python -m src.main --case HHG-017  # single case, for debugging
"""
from __future__ import annotations

import argparse
import csv
import logging
import time

from .config import ANSWERS_DIR, DATA_DIR, GRAPH_BACKEND, get_mcp_client
from .csv_store import get_store
from .orchestrator import build_graph
from .state import InvestigationState, TriggerType

log = logging.getLogger(__name__)


def load_case_pack() -> list[dict]:
    with open(DATA_DIR / "case_pack.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _as_state(result) -> InvestigationState:
    if isinstance(result, InvestigationState):
        return result
    if isinstance(result, dict):
        return InvestigationState.model_validate(result)
    return InvestigationState.model_validate(result)


def run_case(row: dict, graph) -> None:
    state = InvestigationState(
        case_id=row["case_id"],
        trigger_type=TriggerType(row["trigger_type"]),
        trigger_text=row["trigger_text"],
        flagged_txn_id=str(row["flagged_txn_id"]),
        card_id=row["card_id"],
        customer_id=row["customer_id"],
        risk_score=float(row["risk_score"]) if row.get("risk_score") else None,
    )
    t0 = time.time()
    final_state = _as_state(graph.invoke(state))
    final_state.latency_s = round(time.time() - t0, 2)
    ANSWERS_DIR.mkdir(parents=True, exist_ok=True)
    out = ANSWERS_DIR / f"{row['case_id']}.json"
    out.write_text(final_state.to_answer().model_dump_json(indent=2), encoding="utf-8")
    case = final_state.case
    print(
        f"{row['case_id']}: status={case.status.value if case else '?'} "
        f"verdict={case.verdict.value if case else '?'} "
        f"pattern={case.pattern.value if case else '?'} "
        f"latency={final_state.latency_s}s"
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", help="Run a single case_id instead of all 20")
    args = parser.parse_args()

    ANSWERS_DIR.mkdir(parents=True, exist_ok=True)
    if GRAPH_BACKEND == "csv":
        log.info("Using CSV development graph from %s", DATA_DIR)
        get_store()
    elif GRAPH_BACKEND == "tigergraph":
        log.info("Using TigerGraph MCP backend")
        get_mcp_client()
    else:
        raise SystemExit("GRAPH_BACKEND must be 'csv' or 'tigergraph'")
    graph = build_graph()
    rows = load_case_pack()
    if args.case:
        rows = [r for r in rows if r["case_id"] == args.case]
        if not rows:
            raise SystemExit(f"No case {args.case} in case_pack.csv")

    try:
        for row in rows:
            run_case(row, graph)
    finally:
        if GRAPH_BACKEND == "tigergraph":
            get_mcp_client().close()
            get_mcp_client.cache_clear()


if __name__ == "__main__":
    main()
