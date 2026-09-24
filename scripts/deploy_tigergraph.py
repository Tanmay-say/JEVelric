"""Verify the manually loaded graph and install its GSQL query files."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config
from src.mcp_client import TigerGraphMCPClient


def _checked(client: TigerGraphMCPClient, tool: str, **arguments):
    result = client.call_tool(tool, arguments)
    if isinstance(result, dict) and result.get("success") is False:
        raise RuntimeError(f"{tool} failed: {result.get('error') or result}")
    return result


def deploy() -> None:
    if not config.tigergraph_configured():
        raise SystemExit("Set TG_HOST and TG_SECRET in .env before using TigerGraph.")
    client = TigerGraphMCPClient(config.TG_HOST, config.TG_SECRET, config.TG_GRAPH_NAME)
    try:
        stats = _checked(client, "tigergraph__get_vertex_count", graph_name=config.TG_GRAPH_NAME, vertex_type="Transaction")
        count = stats.get("count") if isinstance(stats, dict) else None
        if int(count or 0) != 590742:
            raise RuntimeError(f"Expected 590742 Transaction vertices before query install; found {count!r}.")
        print(f"Transaction count verified: {count}")
        for query_path in sorted((ROOT / "schema" / "queries").glob("*.gsql")):
            _checked(client, "tigergraph__install_query", query_text=query_path.read_text(encoding="utf-8"), graph_name=config.TG_GRAPH_NAME)
    finally:
        client.close()


if __name__ == "__main__":
    deploy()
