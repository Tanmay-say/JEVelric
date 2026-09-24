"""Measure the actual token-bounded text returned by GRIP's formatter."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.grip_client import GripMCPClient

query = "card testing: small online authorizations then larger purchase; policy R5"
report: dict = {"query": query, "weights": {"vector": 0.7, "graph": 0.3}}
with GripMCPClient() as client:
    started = time.perf_counter()
    hybrid = client.call_tool("graphrag_hybrid_search", {
        "query": query, "vector_weight": 0.7, "graph_weight": 0.3,
        "depth": 2, "top_k": 12, "format_text": "none",
    }, timeout_seconds=180)
    report["hybrid_seconds"] = round(time.perf_counter() - started, 3)
    report["hybrid_note"] = (hybrid.get("query") or {}).get("note")
    report["entity_count"] = len((hybrid.get("results") or {}).get("entities") or [])
    started = time.perf_counter()
    formatted = client.call_tool("graphrag_format", {
        "context": hybrid, "format_text": "markdown", "max_tokens": 1200,
    }, timeout_seconds=60)
    report["format_seconds"] = round(time.perf_counter() - started, 3)
    report["formatted_characters"] = len(formatted)
    report["formatted_word_count"] = len(formatted.split())
    report["formatted_preview"] = formatted[:1200]
    similar_started = time.perf_counter()
    similarity = client.call_tool("graphrag_batch_similarity", {
        "anchor": query,
        "candidates": [
            "pattern: card testing; outcome: confirmed_fraud; notes: small online authorizations followed by a larger purchase",
            "pattern: account takeover; outcome: confirmed_fraud; notes: mixed channel transactions and new device",
        ],
    }, timeout_seconds=90)
    report["batch_similarity_seconds"] = round(time.perf_counter() - similar_started, 3)
    report["batch_similarity_methods"] = [x.get("method") for x in similarity]

out = ROOT / "reports" / "grip_ablation" / "format_benchmark.json"
out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps({k: v for k, v in report.items() if k != "formatted_preview"}, indent=2))
