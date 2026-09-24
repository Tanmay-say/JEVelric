"""Round-trip a disposable InvestigationCase vertex through the live graph."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config, graph_client
from src.state import Case, CaseStatus, Pattern, Verdict


def main() -> None:
    config.GRAPH_BACKEND = "tigergraph"
    case_id = "CODEX-WRITE-SMOKE"
    customer_id = "C04570"
    graph_id = f"G-{case_id}"
    case = Case(
        status=CaseStatus.open,
        verdict=Verdict.uncertain,
        fraud_probability=0.4,
        pattern=Pattern.none,
        summary="Temporary live write-path smoke record.",
    )
    try:
        written = graph_client.write_case(case, case_id, customer_id)
        ids = graph_client.known_ids_for("C04570-K1", customer_id)
        if written != graph_id or case_id not in ids or graph_id not in ids:
            raise AssertionError(f"Case write/known-id round trip failed: {written=}, ids={sorted(ids)}")
        print(f"WRITE_OK graph_case_id={written} known_ids={len(ids)}")
    finally:
        result = config.get_mcp_client().call_tool("tigergraph__delete_node", {
            "graph_name": config.TG_GRAPH_NAME,
            "vertex_type": "InvestigationCase",
            "vertex_id": graph_id,
        })
        print(f"CLEANUP {result}")


if __name__ == "__main__":
    main()
