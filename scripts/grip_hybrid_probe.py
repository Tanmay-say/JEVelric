"""Compare live GRIP vector/graph weight splits on corpus-only relevance checks."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.grip_client import GripMCPClient

QUERIES = {
    "card_testing": "three small online authorizations followed by a larger purchase; card testing policy R5",
    "shared_origin": "same device, region, or email shared across multiple cards; monitor connected cards",
    "customer_denial": "customer denies a transaction and exposure requires blocking and a suspicious activity report",
}
WEIGHTS = ((0.5, 0.5), (0.7, 0.3), (0.8, 0.2))
OUT = ROOT / "reports" / "grip_ablation" / "hybrid_weight_probe.json"


def main() -> None:
    report: dict = {"graph": "HHGOA", "weights_tested": [], "queries": {}}
    with GripMCPClient() as client:
        status = client.call_tool("graphrag_status", {})
        if (status.get("backend") or {}).get("graph_id") != "HHGOA":
            raise RuntimeError(f"GRIP is not connected to HHGOA: {status}")
        for query_name, query in QUERIES.items():
            query_results = {}
            for vector_weight, graph_weight in WEIGHTS:
                result = client.call_tool("graphrag_hybrid_search", {
                    "query": query,
                    "vector_weight": vector_weight,
                    "graph_weight": graph_weight,
                    "depth": 2,
                    "top_k": 10,
                    "format_text": "none",
                }, timeout_seconds=90)
                if result.get("error"):
                    raise RuntimeError(f"Hybrid search {query_name} failed: {result}")
                entities = (result.get("results") or {}).get("entities") or []
                query_results[f"{vector_weight:.1f}/{graph_weight:.1f}"] = {
                    "entities": entities,
                    "used_vector_search": bool((result.get("query") or {}).get("note") == "vector"),
                    "query_meta": result.get("query"),
                    "latency_ms": (result.get("metrics") or {}).get("latency_ms"),
                }
            report["queries"][query_name] = query_results
        report["weights_tested"] = [
            {"vector_weight": v, "graph_weight": g} for v, g in WEIGHTS
        ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        name: {
            weights: {
                "used_vector_search": result["used_vector_search"],
                "top_ids": [e.get("id") for e in result["entities"][:5]],
                "latency_ms": result["latency_ms"],
            }
            for weights, result in rows.items()
        }
        for name, rows in report["queries"].items()
    }, indent=2))


if __name__ == "__main__":
    main()
