"""Fix empty GRIP entity types so their primary IDs are exposed as `name`."""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from pyTigerGraph import TigerGraphConnection

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
conn = TigerGraphConnection(
    host=os.getenv("TG_HOST", ""),
    graphname=os.getenv("TG_GRAPHNAME") or "HHGOA",
    gsqlSecret=os.getenv("TG_SECRET", ""),
    username="tigergraph",
    tgCloud=True,
)
counts = {name: int(conn.getVertexCount(name)) for name in ("Author", "Concept")}
edge_counts = {name: int(conn.getEdgeCount(name)) for name in ("AUTHORED_BY", "MENTIONS")}
if any(counts.values()) or any(edge_counts.values()):
    raise SystemExit(f"Refusing to drop nonempty GRIP entity types: vertices={counts}, edges={edge_counts}")

script = (ROOT / "schema" / "grip_fix_entity_schema.gsql").read_text(encoding="utf-8")
schema = conn.getSchema()
entity_schema_ok = all(
    (item := next((v for v in schema.get("VertexTypes", []) if v.get("Name") == name), None))
    and item.get("PrimaryId", {}).get("AttributeName") == "name"
    and item.get("PrimaryId", {}).get("PrimaryIdAsAttribute") is True
    for name in ("Author", "Concept")
)
if not entity_schema_ok:
    result = conn.gsql(script)
    print("schema_change_response:", result)
else:
    print("Author/Concept primary IDs already verified; no schema write performed.")
schema = conn.getSchema()
for name in ("Author", "Concept"):
    item = next((v for v in schema.get("VertexTypes", []) if v.get("Name") == name), None)
    if not item or item.get("PrimaryId", {}).get("AttributeName") != "name":
        raise SystemExit(f"{name} primary ID not found after schema change")
    # pyTigerGraph exposes PRIMARY_ID_AS_ATTRIBUTE under PrimaryId, not
    # Attributes (the regular attribute list remains empty).
    if item.get("PrimaryId", {}).get("PrimaryIdAsAttribute") is not True:
        raise SystemExit(f"{name}.name is not marked PRIMARY_ID_AS_ATTRIBUTE")
if len(schema.get("VertexTypes", [])) != 12 or len(schema.get("EdgeTypes", [])) != 15:
    raise SystemExit("Entity schema repair changed the expected GRIP topology")
print(json.dumps({
    "vertices": len(schema["VertexTypes"]),
    "edges": len(schema["EdgeTypes"]),
    "Author.name_attribute": True,
    "Concept.name_attribute": True,
    "Paper_vertices_preserved": int(conn.getVertexCount("Paper")),
}, indent=2))
