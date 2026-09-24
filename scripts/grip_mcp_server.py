"""Start GRIP MCP with HHGOA and Cloudflare embeddings.

This isolated launcher fails closed instead of accepting GRIP's built-in demo
adapter. Its optional bulk ingestion path is enabled only for verified-empty
document types and preserves the GRIP MCP tool contract.
"""
from __future__ import annotations

import functools
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
TRUSTED_PAPER_IDS: set[str] | None = None
load_dotenv(ROOT / ".env")
host = os.getenv("TG_HOST", "").strip()
secret = os.getenv("TG_SECRET", "").strip()
graph = (os.getenv("TG_GRAPHNAME") or "HHGOA").strip()
cf_token = os.getenv("CF_API_TOKEN", "").strip()
cf_account = os.getenv("CF_ACCOUNT_ID", "").strip()
if not host or not secret or graph != "HHGOA":
    raise RuntimeError("GRIP requires TG_HOST, TG_SECRET, and TG_GRAPHNAME=HHGOA")
if not cf_token or not cf_account:
    raise RuntimeError("GRIP vector search requires CF_API_TOKEN and CF_ACCOUNT_ID")

os.environ["TIGERGRAPH_HOST"] = host
os.environ["TIGERGRAPH_GSQL_SECRET"] = secret
os.environ["TIGERGRAPH_GRAPH_NAME"] = graph
os.environ["TG_GRAPH"] = graph

embedding_client = OpenAI(
    api_key=cf_token,
    base_url=f"https://api.cloudflare.com/client/v4/accounts/{cf_account}/ai/v1",
    timeout=60.0,
)


def corpus_document_ids() -> set[str]:
    path = ROOT / "data" / "grip_corpus" / "documents.jsonl"
    with path.open(encoding="utf-8") as handle:
        return {str(json.loads(line).get("id")) for line in handle if line.strip()}


def existing_paper_ids(conn, expected_ids: set[str]) -> set[str]:
    result = conn.getVertices("Paper", select="title", limit=6000)
    found = {
        str(item.get("v_id")) for item in result
        if isinstance(item, dict) and item.get("v_id") is not None
    }
    unexpected = found - expected_ids
    if unexpected:
        raise RuntimeError(f"Paper vertices are outside prepared corpus: {sorted(unexpected)[:10]}")
    return found


def wait_for_paper_ids(conn, expected_ids: set[str], timeout_seconds: int = 90) -> set[str]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        found = existing_paper_ids(conn, expected_ids)
        if expected_ids.issubset(found):
            return found
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"Paper writes did not become query-visible: expected={len(expected_ids)}, "
                f"visible={len(found)}"
            )
        time.sleep(2)


@functools.lru_cache(maxsize=4096)
def embed_text(text: str) -> tuple[float, ...]:
    response = embedding_client.embeddings.create(
        model="@cf/baai/bge-base-en-v1.5", input=text
    )
    vector = response.data[0].embedding
    if len(vector) != 768:
        raise RuntimeError(f"Cloudflare embedding dimension mismatch: {len(vector)}")
    return tuple(float(v) for v in vector)


from mcp_server.adapters import TigerGraphAdapter  # noqa: E402
from mcp_server.contracts.construction import ConstructionContract  # noqa: E402
from mcp_server.mcp_server import main as grip_main  # noqa: E402
from mcp_server.protocol_extensions import IngestionReport  # noqa: E402
import mcp_server.mcp_server as grip  # noqa: E402
from mcp_server.contracts.retrieval import RetrievalContract  # noqa: E402


# GRIP 0.5.0's RetrievalContract drops the adapter's `query.note` field when
# normalizing SubgraphContext. Preserve this diagnostic so callers can tell
# vector+graph fusion from keyword-only fallback in actual MCP responses.
_original_build_response = RetrievalContract.build_response


def _build_response_with_retrieval_note(self, *args, **kwargs):
    raw = kwargs.get("raw")
    if raw is None and len(args) >= 3:
        raw = args[2]
    note = getattr(raw, "query", {}).get("note") if raw is not None else None
    result = _original_build_response(self, *args, **kwargs)
    if note:
        result.query["note"] = note
    return result


RetrievalContract.build_response = _build_response_with_retrieval_note


def batched_ingest(self, documents, config=None):
    """Bulk REST++ upserts behind the package's normal graphrag_ingest tool."""
    if os.getenv("GRIP_FAST_EMPTY_INGEST") != "1":
        raise RuntimeError("Bulk ingestion is disabled outside its guarded initialization run")
    if config is None:
        raise RuntimeError("GRIP ingestion config was not supplied")
    started = time.perf_counter()
    conn = self._conn
    types = ("Paper", "Author", "Concept", "PaperEmb")
    before = {name: int(conn.getVertexCount(name)) for name in types}
    # The earlier failed attempt wrote exactly the four policy chunks before
    # the schema error. Allow those known, idempotently-upserted records only.
    known_papers = TRUSTED_PAPER_IDS or set()
    visible_papers = existing_paper_ids(conn, corpus_document_ids())
    if visible_papers != known_papers or before["PaperEmb"]:
        raise RuntimeError(
            f"Corpus live rows do not reconcile before batch; count_api={before}, "
            f"visible_papers={len(visible_papers)}, tracked_papers={len(known_papers)}"
        )

    report = IngestionReport(
        graph_id=config.graph_id,
        document_ids=[str(d.get("id", "")) for d in documents if d.get("id")],
    )
    report.vertices_before = before
    papers: list[tuple[str, dict]] = []
    entities: dict[str, dict[str, dict]] = {"Author": {}, "Concept": {}}
    edge_groups: dict[tuple[str, str, str], list[tuple[str, str, dict]]] = {}
    for doc in documents:
        doc_id = str(doc.get("id") or "").strip()
        if not doc_id:
            report.errors.append("document missing 'id'; skipped")
            continue
        categories = doc.get("categories") or []
        papers.append((doc_id, {
            "title": str(doc.get("title") or ""),
            "abstract": str(doc.get("abstract") or doc.get("content") or ""),
            "categories": ", ".join(categories) if isinstance(categories, list) else str(categories),
            "abstract_token_count": int(doc.get("abstract_token_count") or 0),
        }))
        triples = self.extract_entities(doc, config)
        report.triples_extracted += len(triples)
        for triple in triples:
            entities.setdefault(triple.object_type, {})[triple.object_id] = (
                {"name": triple.object_id} if triple.object_type in {"Author", "Concept"} else {}
            )
            key = (triple.subject_type, triple.predicate, triple.object_type)
            edge_groups.setdefault(key, []).append((triple.subject_id, triple.object_id, {}))

    if papers:
        accepted = conn.upsertVertices("Paper", papers)
        if accepted != len(papers):
            raise RuntimeError(f"Paper upsert accepted {accepted}/{len(papers)}")
        known_papers.update(doc_id for doc_id, _ in papers)
    for entity_type in ("Author", "Concept"):
        values = list(entities.get(entity_type, {}).items())
        if values:
            accepted = conn.upsertVertices(entity_type, values)
            if accepted != len(values):
                raise RuntimeError(f"{entity_type} upsert accepted {accepted}/{len(values)}")
    edge_count = 0
    for (source_type, edge_type, target_type), edges in edge_groups.items():
        accepted = conn.upsertEdges(
            source_type, edge_type, target_type, edges, vertexMustExist=True
        )
        if accepted != len(edges):
            raise RuntimeError(f"{edge_type} upsert accepted {accepted}/{len(edges)}")
        edge_count += accepted

    report.documents_ingested = len(papers)
    report.documents_written = [doc_id for doc_id, _ in papers]
    report.documents_created = list(report.documents_written)
    report.entities_created = len(papers) + sum(
        len(entities.get(name, {})) for name in ("Author", "Concept")
    )
    report.edges_created = edge_count
    visible_papers = wait_for_paper_ids(conn, known_papers)
    report.vertices_after = {name: int(conn.getVertexCount(name)) for name in types}
    report.vertices_after["Paper"] = len(visible_papers)
    report.duration_ms = round((time.perf_counter() - started) * 1000, 2)
    return report


def configured_adapter():
    global TRUSTED_PAPER_IDS
    adapter = TigerGraphAdapter(embedder=lambda text: list(embed_text(text)))
    health = adapter.health_check()
    if health.get("status") != "ok" or health.get("graph_id") != graph:
        raise RuntimeError(f"GRIP TigerGraph adapter failed closed: {health}")
    if os.getenv("GRIP_FAST_EMPTY_INGEST") == "1":
        expected_ids = corpus_document_ids()
        counts = {
            name: int(adapter.conn.getVertexCount(name))
            for name in ("Paper", "Author", "Concept", "PaperEmb")
        }
        known_papers = existing_paper_ids(adapter.conn, expected_ids)
        if (counts["Paper"] != len(known_papers)
                or counts["PaperEmb"] != 0
                or any(counts[name] > len(expected_ids) for name in ("Author", "Concept"))):
            raise RuntimeError(
                f"Unexpected partial corpus state; counts={counts}, "
                f"known_paper_count={len(known_papers)}"
            )
        TRUSTED_PAPER_IDS = known_papers
        ConstructionContract.ingest = batched_ingest
    return adapter


grip._adapter = configured_adapter
grip_main()
