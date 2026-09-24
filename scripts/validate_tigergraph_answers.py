"""Validate all case-pack answers against schema rules and live TigerGraph IDs."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config, graph_client
from src.config import get_mcp_client
from src.orchestrator import _ids_from_evidence
from src.state import Answer
from src.validate import validate_answer


def main() -> int:
    config.GRAPH_BACKEND = "tigergraph"
    with (config.DATA_DIR / "case_pack.csv").open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))

    expected = {row["case_id"]: row for row in rows}
    answer_paths = {path.stem: path for path in config.ANSWERS_DIR.glob("HHG-*.json")}
    failures: dict[str, list[str]] = {}
    if set(answer_paths) != set(expected):
        missing = sorted(set(expected) - set(answer_paths))
        extra = sorted(set(answer_paths) - set(expected))
        failures["file_set"] = [f"missing={missing}", f"extra={extra}"]

    client = get_mcp_client()
    try:
        live_count = client.call_tool(
            "tigergraph__get_vertex_count",
            {"graph_name": config.TG_GRAPH_NAME, "vertex_type": "Transaction"},
        )
        if int(live_count.get("count", -1)) != 590742:
            failures["Transaction_count"] = [f"expected 590742, got {live_count}"]

        for case_id, row in expected.items():
            path = answer_paths.get(case_id)
            if path is None:
                continue
            problems: list[str] = []
            try:
                answer = Answer.model_validate_json(path.read_text(encoding="utf-8"))
                if answer.case_id != case_id:
                    problems.append(f"top-level case_id is {answer.case_id!r}")
                if not answer.case.written_to_graph:
                    problems.append("case.written_to_graph is false")
                if answer.case.graph_case_id != f"G-{case_id}":
                    problems.append(f"case.graph_case_id is {answer.case.graph_case_id!r}")

                graph_evidence = graph_client.retrieve_all(
                    card_id=row["card_id"],
                    customer_id=row["customer_id"],
                    flagged_txn_id=str(row["flagged_txn_id"]),
                )
                known_ids = graph_client.known_ids_for(row["card_id"], row["customer_id"])
                known_ids |= _ids_from_evidence(graph_evidence)
                known_ids.update((row["card_id"], row["customer_id"], str(row["flagged_txn_id"])))
                problems.extend(validate_answer(answer, known_ids))
            except Exception as exc:
                problems.append(f"{type(exc).__name__}: {exc}")
            if problems:
                failures[case_id] = problems
            else:
                print(f"{case_id}: valid")
    finally:
        client.close()
        get_mcp_client.cache_clear()

    print(json.dumps({"checked": len(expected), "failed": failures}, indent=2, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
