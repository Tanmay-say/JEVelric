"""Ingest the prepared text-only corpus through GRIP's graphrag_ingest MCP tool."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.grip_client import GripMCPClient

CORPUS = ROOT / "data" / "grip_corpus" / "documents.jsonl"
REPORT = ROOT / "reports" / "grip_ablation" / "ingest_report.json"
BATCH_SIZE = 50


def load_documents() -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    with CORPUS.open(encoding="utf-8") as handle:
        for line in handle:
            doc = json.loads(line)
            collection = (doc.get("categories") or ["unknown"])[0]
            groups[collection].append(doc)
    return dict(groups)


def main() -> None:
    collections = load_documents()
    aggregate = {
        "graph": "HHGOA",
        "mcp_tool": "graphrag_ingest",
        "extraction_strategy": "frequency",
        "async_mode": False,
        "batch_size": BATCH_SIZE,
        "collections": {},
    }
    with GripMCPClient(fast_empty_ingest=True) as client:
        status = client.call_tool("graphrag_status", {})
        backend = status.get("backend") or {}
        if backend.get("backend") != "tigergraph" or backend.get("graph_id") != "HHGOA":
            raise RuntimeError(f"GRIP failed live HHGOA preflight: {backend}")
        schema = client.call_tool("graphrag_schema", {"graph_id": "HHGOA"})
        if len(schema.get("vertex_types", [])) != 12 or len(schema.get("edge_types", [])) != 15:
            raise RuntimeError("GRIP schema changed after vector schema verification")

        for collection in ("policy", "patterns", "closed_case"):
            docs = collections.get(collection, [])
            collection_report = {
                "documents_expected": len(docs),
                "chunks_expected": len(docs),
                "documents_ingested": 0,
                "triples_extracted": 0,
                "entities_created_reported": 0,
                "edges_created": 0,
                "batches": 0,
            }
            for offset in range(0, len(docs), BATCH_SIZE):
                batch = docs[offset:offset + BATCH_SIZE]
                result = client.call_tool("graphrag_ingest", {
                    "documents": batch,
                    "extraction_strategy": "frequency",
                    "admin_token": client.admin_token,
                    "async_mode": False,
                }, timeout_seconds=180)
                if not isinstance(result, dict):
                    raise RuntimeError(f"graphrag_ingest returned an unexpected response: {result!r}")
                if result.get("error") or result.get("errors"):
                    raise RuntimeError(f"graphrag_ingest failed for {collection} batch {offset // BATCH_SIZE + 1}: {result}")
                count = int(result.get("documents_ingested") or 0)
                if count != len(batch):
                    raise RuntimeError(
                        f"graphrag_ingest accepted {count}/{len(batch)} {collection} documents: {result}"
                    )
                collection_report["documents_ingested"] += count
                collection_report["triples_extracted"] += int(result.get("triples_extracted") or 0)
                collection_report["entities_created_reported"] += int(result.get("entities_created") or 0)
                collection_report["edges_created"] += int(result.get("edges_created") or 0)
                collection_report["batches"] += 1
                collection_report["last_vertex_counts"] = result.get("vertices_after")
                aggregate["collections"][collection] = collection_report
                REPORT.parent.mkdir(parents=True, exist_ok=True)
                REPORT.write_text(json.dumps(aggregate, indent=2) + "\n", encoding="utf-8")
                print(json.dumps({
                    "collection": collection,
                    "batch": collection_report["batches"],
                    "documents": collection_report["documents_ingested"],
                    "expected": len(docs),
                    "live_counts": collection_report.get("last_vertex_counts"),
                }, ensure_ascii=False))
            if collection_report["documents_ingested"] != len(docs):
                raise RuntimeError(f"Collection {collection} ended short: {collection_report}")

    REPORT.write_text(json.dumps(aggregate, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(aggregate, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
