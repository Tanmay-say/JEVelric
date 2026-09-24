"""Install and compare exactly one TigerGraph retrieval query against CSV."""
from __future__ import annotations

import csv
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config, graph_client

QUERY_FILES = {
    "card_window": "card_window.gsql",
    "device_neighbors": "device_neighbors.gsql",
    "region_cluster": "region_cluster.gsql",
    "email_cluster": "email_cluster.gsql",
    "closed_case_similarity": "closed_case_similarity.gsql",
    "customer_history": "customer_history.gsql",
}


def run_query(name: str, case: dict) -> dict:
    txn, card, customer = case["flagged_txn_id"], case["card_id"], case["customer_id"]
    if name == "card_window":
        return graph_client.card_window(card, hours=config.CARD_WINDOW_HOURS, flagged_txn_id=txn)
    if name == "device_neighbors":
        return graph_client.device_neighbors_for_txn(txn)
    if name == "region_cluster":
        return graph_client.region_cluster_for_txn(txn, 7)
    if name == "email_cluster":
        return graph_client.email_cluster_for_txn(txn, 7)
    if name == "closed_case_similarity":
        return graph_client.closed_case_similarity(customer, card)
    if name == "customer_history":
        return graph_client.customer_history(customer)
    raise ValueError(f"Unknown query: {name}")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if len(sys.argv) != 2 or sys.argv[1] not in QUERY_FILES:
        raise SystemExit(f"Usage: {Path(sys.argv[0]).name} <{'|'.join(QUERY_FILES)}>")
    name = sys.argv[1]
    with (config.DATA_DIR / "case_pack.csv").open(newline="", encoding="utf-8-sig") as stream:
        case = next(row for row in csv.DictReader(stream) if row["case_id"] == "HHG-017")

    query_text = (ROOT / "schema" / "queries" / QUERY_FILES[name]).read_text(encoding="utf-8")
    client = config.get_mcp_client()
    installed = client.call_tool("tigergraph__install_query", {
        "graph_name": config.TG_GRAPH_NAME,
        "query_text": query_text,
    })
    print("INSTALL", json.dumps(installed, ensure_ascii=False, default=str))

    config.GRAPH_BACKEND = "csv"
    csv_result = run_query(name, case)
    config.GRAPH_BACKEND = "tigergraph"
    tg_result = run_query(name, case)
    same = csv_result == tg_result
    report = {
        "case_id": "HHG-017",
        "query": name,
        "same": same,
        "csv": csv_result,
        "tigergraph": tg_result,
    }
    out = ROOT / "reports" / "query_comparisons"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"HHG-017_{name}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print("COMPARISON", json.dumps({"query": name, "same": same, "report": str(path),
                                   "csv_summary": _summary(csv_result), "tigergraph_summary": _summary(tg_result)},
                                  ensure_ascii=False, default=str))
    return 0 if same else 2


def _summary(value):
    if isinstance(value, dict):
        return {key: (len(item) if isinstance(item, (list, dict)) else item) for key, item in value.items()}
    return len(value) if isinstance(value, list) else value


if __name__ == "__main__":
    raise SystemExit(main())
