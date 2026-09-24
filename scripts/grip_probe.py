"""Phase 1 read-only GRIP MCP connectivity and schema probe.

This calls GRIP's MCP tools against the existing HHGOA TigerGraph graph.
Credentials are passed only to the child process and are never printed.
"""
from __future__ import annotations

import asyncio
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "reports" / "grip_ablation" / "phase1_raw_tools.json"
load_dotenv(ROOT / ".env")

required = {
    "TG_HOST": os.getenv("TG_HOST", "").strip(),
    "TG_SECRET": os.getenv("TG_SECRET", "").strip(),
    "TG_GRAPHNAME": os.getenv("TG_GRAPHNAME", "HHGOA").strip(),
}
missing = [key for key, value in required.items() if not value]
if missing:
    raise SystemExit("Missing required settings: " + ", ".join(missing))

child_env = os.environ.copy()
child_env.update(
    {
        "TIGERGRAPH_HOST": required["TG_HOST"],
        "TIGERGRAPH_GSQL_SECRET": required["TG_SECRET"],
        "TIGERGRAPH_GRAPH_NAME": required["TG_GRAPHNAME"],
        "TG_GRAPH": required["TG_GRAPHNAME"],
    }
)

preflight_code = """
from mcp_server.adapters.tigergraph_adapter import TigerGraphAdapter
import os
print({k: bool(os.getenv(k)) for k in ('TIGERGRAPH_HOST', 'TIGERGRAPH_GRAPH_NAME', 'TIGERGRAPH_GSQL_SECRET')})
print(TigerGraphAdapter().health_check())
"""
preflight = subprocess.run(
    [sys.executable, "-c", preflight_code],
    cwd=ROOT,
    env=child_env,
    capture_output=True,
    text=True,
    check=False,
)
print("=== child-process TigerGraph adapter preflight ===")
print(preflight.stdout.strip())
if preflight.stderr.strip():
    print(preflight.stderr.strip())
if preflight.returncode:
    raise SystemExit("GRIP adapter preflight failed")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    output_path = args.output.resolve()
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server.mcp_server"],
        env=child_env,
        cwd=str(ROOT),
    )
    raw_outputs: dict[str, object] = {}
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as server_stderr:
        async with stdio_client(server, errlog=server_stderr) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                names = (
                    "graphrag_status",
                    "graphrag_schema",
                    "graphrag_entity_types",
                    "graphrag_relationship_types",
                )
                for name in names:
                    result = await session.call_tool(name, {"graph_id": required["TG_GRAPHNAME"]} if name != "graphrag_status" else {})
                    raw = "\n".join(item.text for item in result.content if hasattr(item, "text"))
                    if result.is_error:
                        raise SystemExit(f"GRIP MCP tool failed: {name}")
                    raw_outputs[name] = json.loads(raw) if raw else result.model_dump(mode="json")
                    if name == "graphrag_status":
                        status = raw_outputs[name]
                        backend = status.get("backend") or {}
                        if backend.get("backend") != "tigergraph" or backend.get("graph_id") != required["TG_GRAPHNAME"]:
                            server_stderr.flush()
                            server_stderr.seek(0)
                            diagnostics = server_stderr.read().strip()
                            if diagnostics:
                                print("=== GRIP server stderr ===")
                                print(diagnostics)
                            raise SystemExit(
                                "STOP: GRIP status does not identify the configured HHGOA TigerGraph graph. "
                                f"Observed backend={backend.get('backend')!r}, graph_id={backend.get('graph_id')!r}."
                            )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(raw_outputs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    status = raw_outputs["graphrag_status"]
    schema = raw_outputs["graphrag_schema"]
    vertex_types = raw_outputs["graphrag_entity_types"]
    edge_types = raw_outputs["graphrag_relationship_types"]
    errors = []
    core_vertices = {
        "Customer", "Card", "Transaction", "DeviceProfile", "EmailDomain",
        "BillingRegion", "ClosedCase", "InvestigationCase",
    }
    grip_vertices = {"Paper", "Author", "Concept", "PaperEmb"}
    core_edges = {
        "OWNS", "MADE", "FROM_DEVICE", "PURCHASER_EMAIL", "BILLED_IN", "NEXT",
        "INVOLVES", "ON_CARD", "CONNECTED_TO", "INVESTIGATES", "CASE_ON_CARD",
        "CITES", "CASE_FROM_DEVICE",
    }
    grip_edges = {"AUTHORED_BY", "MENTIONS"}
    schema_vertex_types = {v.get("type") for v in schema.get("vertex_types", [])}
    listed_vertex_types = {v.get("type") for v in vertex_types}
    schema_edge_types = {e.get("type") for e in schema.get("edge_types", [])}
    listed_edge_types = {e.get("type") for e in edge_types}
    if schema.get("graph_id") != required["TG_GRAPHNAME"]:
        errors.append(f"schema graph_id={schema.get('graph_id')!r}")
    if schema_vertex_types != core_vertices | grip_vertices or listed_vertex_types != schema_vertex_types:
        errors.append(f"vertex types do not match HHGOA + GRIP topology: {sorted(schema_vertex_types)}")
    if schema_edge_types != core_edges | grip_edges or listed_edge_types != schema_edge_types:
        errors.append(f"edge types do not match HHGOA + GRIP topology: {sorted(schema_edge_types)}")
    if schema_vertex_types != listed_vertex_types:
        errors.append("vertex type listing differs from full schema")
    if schema_edge_types != listed_edge_types:
        errors.append("relationship type listing differs from full schema")
    transaction = next((v for v in schema.get("vertex_types", []) if v.get("type") == "Transaction"), {})
    if transaction.get("count") != 590742:
        errors.append(f"Transaction count expected 590742, got {transaction.get('count')!r}")
    if (status.get("statistics") or {}).get("total_vertices", 0) <= 590742:
        errors.append(f"status vertex total is too small for HHGOA: {(status.get('statistics') or {}).get('total_vertices')!r}")
    if errors:
        raise SystemExit("GRIP schema verification failed: " + "; ".join(errors))
    print(json.dumps({
        "status": status,
        "graph_id": schema.get("graph_id"),
        "vertex_type_count": len(vertex_types),
        "edge_type_count": len(edge_types),
        "vertex_types": sorted(listed_vertex_types),
        "edge_types": sorted(listed_edge_types),
        "raw_output_file": str(output_path.relative_to(ROOT)),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
