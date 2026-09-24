"""Embed every prepared GRIP text document with Cloudflare BGE and upsert it."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from pyTigerGraph import TigerGraphConnection

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
CORPUS = ROOT / "data" / "grip_corpus" / "documents.jsonl"
REPORT = ROOT / "reports" / "grip_ablation" / "embedding_report.json"
MODEL = "@cf/baai/bge-base-en-v1.5"
DIMENSION = 768
BATCH_SIZE = 32


def main() -> None:
    host = os.getenv("TG_HOST", "").strip()
    secret = os.getenv("TG_SECRET", "").strip()
    graph = (os.getenv("TG_GRAPHNAME") or "HHGOA").strip()
    token = os.getenv("CF_API_TOKEN", "").strip()
    account = os.getenv("CF_ACCOUNT_ID", "").strip()
    if not all((host, secret, token, account)) or graph != "HHGOA":
        raise RuntimeError("Embedding requires configured HHGOA and Cloudflare credentials")

    docs = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(docs) != 5570 or len({d["id"] for d in docs}) != len(docs):
        raise RuntimeError(f"Expected 5,570 unique corpus documents; found {len(docs)}")

    client = OpenAI(
        api_key=token,
        base_url=f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1",
        timeout=60.0,
    )
    conn = TigerGraphConnection(
        host=host, graphname=graph, gsqlSecret=secret, username="tigergraph", tgCloud=True,
    )
    report = {
        "graph": graph,
        "provider": "Cloudflare Workers AI",
        "model": MODEL,
        "dimension": DIMENSION,
        "documents_expected": len(docs),
        "documents_embedded_and_upserted": 0,
        "batch_size": BATCH_SIZE,
        "batches_completed": 0,
        "started_at_epoch": time.time(),
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)

    for offset in range(0, len(docs), BATCH_SIZE):
        batch = docs[offset:offset + BATCH_SIZE]
        response = client.embeddings.create(
            model=MODEL,
            input=[str(d["abstract"]) for d in batch],
        )
        ordered = sorted(response.data, key=lambda item: item.index)
        if len(ordered) != len(batch):
            raise RuntimeError(f"Cloudflare returned {len(ordered)}/{len(batch)} embeddings")
        vertices = []
        for doc, item in zip(batch, ordered):
            vector = item.embedding
            if len(vector) != DIMENSION:
                raise RuntimeError(f"{doc['id']}: expected {DIMENSION} dims, received {len(vector)}")
            vertices.append((str(doc["id"]), {"abstract_embedding": [float(v) for v in vector]}))
        accepted = conn.upsertVertices("PaperEmb", vertices)
        if accepted != len(vertices):
            raise RuntimeError(f"TigerGraph accepted {accepted}/{len(vertices)} vector vertices")
        report["documents_embedded_and_upserted"] += len(vertices)
        report["batches_completed"] += 1
        report["last_document_id"] = str(batch[-1]["id"])
        report["paperemb_count_api"] = int(conn.getVertexCount("PaperEmb"))
        REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if report["batches_completed"] % 10 == 0:
            print(json.dumps({
                "completed": report["documents_embedded_and_upserted"],
                "expected": len(docs),
                "PaperEmb_count_api": report["paperemb_count_api"],
            }), flush=True)

    final_count = int(conn.getVertexCount("PaperEmb"))
    if final_count != len(docs):
        raise RuntimeError(f"Expected {len(docs)} PaperEmb vertices, live TigerGraph count is {final_count}")
    report["paperemb_count_final"] = final_count
    report["completed_at_epoch"] = time.time()
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
