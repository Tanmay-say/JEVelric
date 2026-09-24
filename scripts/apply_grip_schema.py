"""Apply and verify GRIP's additive document/vector schema on HHGOA."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pyTigerGraph import TigerGraphConnection

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
HOST = os.getenv("TG_HOST", "").strip()
SECRET = os.getenv("TG_SECRET", "").strip()
GRAPH = (os.getenv("TG_GRAPHNAME") or "HHGOA").strip()
if not HOST or not SECRET or GRAPH != "HHGOA":
    raise SystemExit("Expected TG_HOST, TG_SECRET, and TG_GRAPHNAME=HHGOA in .env")

conn = TigerGraphConnection(
    host=HOST,
    graphname=GRAPH,
    gsqlSecret=SECRET,
    username="tigergraph",
    tgCloud=True,
)
schema = conn.getSchema()
vertices = {v["Name"] for v in schema.get("VertexTypes", [])}
edges = {e["Name"] for e in schema.get("EdgeTypes", [])}
add_vertices = {"Paper", "Author", "Concept", "PaperEmb"}
add_edges = {"AUTHORED_BY", "MENTIONS"}

if add_vertices <= vertices and add_edges <= edges:
    emb = next(v for v in schema["VertexTypes"] if v["Name"] == "PaperEmb")
    vector_attrs = emb.get("EmbeddingAttributes", [])
    if not any(a.get("Name") == "abstract_embedding" and a.get("Dimension") == 768 for a in vector_attrs):
        raise SystemExit("GRIP types exist, but PaperEmb.abstract_embedding is not a 768-dim vector")
    print("GRIP schema already present and verified; no schema write performed.")
else:
    if add_vertices & vertices or add_edges & edges:
        raise SystemExit("Partial GRIP schema exists; refusing to apply a potentially conflicting schema change")
    if len(vertices) != 8 or len(edges) != 13:
        raise SystemExit(f"Unexpected starting topology: {len(vertices)} vertices, {len(edges)} edges")
    script = (ROOT / "schema" / "grip_corpus_schema.gsql").read_text(encoding="utf-8")
    result = conn.gsql(script)
    print("schema_change_response:", result)
    schema = conn.getSchema()
    vertices = {v["Name"] for v in schema.get("VertexTypes", [])}
    edges = {e["Name"] for e in schema.get("EdgeTypes", [])}
    if len(vertices) != 12 or len(edges) != 15 or not add_vertices <= vertices or not add_edges <= edges:
        raise SystemExit(f"Post-change topology mismatch: {len(vertices)} vertices, {len(edges)} edges")
    emb = next(v for v in schema["VertexTypes"] if v["Name"] == "PaperEmb")
    if not any(a.get("Name") == "abstract_embedding" and a.get("Dimension") == 768 for a in emb.get("EmbeddingAttributes", [])):
        raise SystemExit("PaperEmb.abstract_embedding vector attribute not reported at dimension 768")
    print("Verified additive schema: 12 vertex types, 15 edge types; PaperEmb.abstract_embedding=768 COSINE.")
