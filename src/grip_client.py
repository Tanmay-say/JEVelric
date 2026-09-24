"""Synchronous facade over the optional GRIP MCP stdio server."""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import secrets
import sys
import threading
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from . import config

log = logging.getLogger(__name__)


class GripMCPClient:
    """Keep one isolated GRIP MCP process alive for a case run."""

    REQUIRED_TOOLS = {
        "graphrag_hybrid_search",
        "graphrag_batch_similarity",
        "graphrag_format",
    }

    def __init__(self, *, fast_empty_ingest: bool = False) -> None:
        if not config.tigergraph_configured():
            raise RuntimeError("GRIP requires the configured HHGOA TigerGraph connection")
        if not config.CF_API_TOKEN or not config.CF_ACCOUNT_ID:
            raise RuntimeError("GRIP requires CF_API_TOKEN and CF_ACCOUNT_ID for dense vectors")
        self.admin_token = secrets.token_urlsafe(32)
        child_env = {
            "TG_HOST": config.TG_HOST,
            "TG_SECRET": config.TG_SECRET,
            "TG_GRAPHNAME": config.TG_GRAPH_NAME,
            "CF_API_TOKEN": config.CF_API_TOKEN,
            "CF_ACCOUNT_ID": config.CF_ACCOUNT_ID,
            "GRAPHRAG_ADMIN_TOKEN": self.admin_token,
            "PYTHON_DOTENV_DISABLED": "true",
        }
        if fast_empty_ingest:
            child_env["GRIP_FAST_EMPTY_INGEST"] = "1"
        server = StdioServerParameters(
            command=sys.executable,
            args=[str(config.ROOT / "scripts" / "grip_mcp_server.py")],
            env=child_env,
            cwd=str(config.ROOT),
        )
        self._loop = asyncio.new_event_loop()
        self._ready: concurrent.futures.Future = concurrent.futures.Future()
        self._thread = threading.Thread(target=self._run_loop, args=(server,), name="grip-mcp-stdio", daemon=True)
        self._thread.start()
        self._ready.result(timeout=90)

    async def _serve(self, server: StdioServerParameters) -> None:
        try:
            async with stdio_client(server) as streams:
                async with ClientSession(*streams) as session:
                    self._session = session
                    await session.initialize()
                    tools = (await session.list_tools()).tools
                    found = {tool.name for tool in tools}
                    missing = self.REQUIRED_TOOLS - found
                    if missing:
                        raise RuntimeError(f"GRIP MCP server missing required tools: {sorted(missing)}")
                    if not self._ready.done():
                        self._ready.set_result(True)
                    await self._stop_event.wait()
        except Exception as exc:
            if not self._ready.done():
                self._ready.set_exception(exc)
            else:
                log.exception("GRIP MCP process failed")

    def _run_loop(self, server: StdioServerParameters) -> None:
        asyncio.set_event_loop(self._loop)
        self._stop_event = asyncio.Event()
        self._serve_task = self._loop.create_task(self._serve(server))
        self._loop.run_until_complete(self._serve_task)
        self._loop.close()

    def call_tool(self, name: str, arguments: dict[str, Any], timeout_seconds: int = 120) -> Any:
        if not self._thread.is_alive() or not hasattr(self, "_session"):
            raise RuntimeError("GRIP MCP process is not running")
        future = asyncio.run_coroutine_threadsafe(
            self._session.call_tool(name, arguments=arguments), self._loop
        )
        result = future.result(timeout=timeout_seconds)
        if getattr(result, "is_error", False):
            raise RuntimeError(f"GRIP MCP tool {name} failed: {self._text(result)}")
        raw = self._text(result)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    @staticmethod
    def _text(result: Any) -> str:
        return "\n".join(
            str(getattr(block, "text", ""))
            for block in (getattr(result, "content", []) or [])
            if getattr(block, "text", None)
        )

    def close(self) -> None:
        if not self._thread.is_alive():
            return
        async def stop_server() -> None:
            self._stop_event.set()

        future = asyncio.run_coroutine_threadsafe(stop_server(), self._loop)
        future.result(timeout=5)
        self._thread.join(timeout=15)

    def __enter__(self) -> "GripMCPClient":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
