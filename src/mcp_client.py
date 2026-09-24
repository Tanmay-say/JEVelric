"""Synchronous facade for a local TigerGraph MCP stdio subprocess."""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import re
import sys
import threading
from contextlib import AsyncExitStack
from typing import Any

from . import config

log = logging.getLogger(__name__)


class TigerGraphMCPClient:
    """Own one long-lived TigerGraph MCP process for the sync LangGraph nodes."""

    def __init__(self, host: str, secret: str, graph_name: str = "HHGOA") -> None:
        self.graph_name = graph_name
        self._loop = asyncio.new_event_loop()
        self._ready: concurrent.futures.Future = concurrent.futures.Future()
        self._session = None
        self._stop: asyncio.Event | None = None
        self._thread = threading.Thread(target=self._run_loop, name="tigergraph-mcp-stdio", daemon=True)
        self._server_env = {
            "TG_HOST": host,
            "TG_SECRET": secret,
            "TG_GRAPHNAME": graph_name,
        }
        self._thread.start()
        try:
            self._ready.result(timeout=30)
        except Exception:
            self._thread.join(timeout=2)
            raise

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._session_lifetime())
        except Exception as exc:
            if not self._ready.done():
                self._ready.set_exception(exc)
            else:
                log.exception("TigerGraph MCP stdio session stopped unexpectedly")
        finally:
            self._loop.close()

    async def _session_lifetime(self) -> None:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "tigergraph_mcp.main"],
            env=self._server_env,
            cwd=str(config.ROOT),
        )
        async with AsyncExitStack() as stack:
            streams = await stack.enter_async_context(stdio_client(server))
            read_stream, write_stream = streams
            self._session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            await self._session.initialize()
            self._stop = asyncio.Event()
            if not self._ready.done():
                self._ready.set_result(True)
            await self._stop.wait()

    def call_tool(self, name: str, arguments: dict[str, Any], timeout_seconds: int = 120) -> Any:
        if not self._thread.is_alive() or self._session is None:
            raise RuntimeError("TigerGraph MCP stdio process is not running")
        future = asyncio.run_coroutine_threadsafe(
            self._session.call_tool(name, arguments=arguments), self._loop
        )
        return self._decode(future.result(timeout=timeout_seconds))

    @staticmethod
    def _decode(result: Any) -> Any:
        if getattr(result, "isError", False):
            raise RuntimeError("TigerGraph MCP returned an error: " + TigerGraphMCPClient._text(result))

        structured = getattr(result, "structuredContent", None)
        payload: Any = structured if structured is not None else None
        if payload is None:
            for block in getattr(result, "content", []) or []:
                text = getattr(block, "text", None)
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    fenced = re.search(r"```json\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
                    if fenced:
                        try:
                            payload = json.loads(fenced.group(1))
                        except json.JSONDecodeError:
                            payload = text
                    else:
                        payload = text
                break
        if isinstance(payload, dict):
            if payload.get("success") is False:
                raise RuntimeError(payload.get("error") or payload.get("summary") or str(payload))
            if "data" in payload:
                return payload["data"]
        return payload

    @staticmethod
    def _text(result: Any) -> str:
        return "\n".join(
            str(getattr(block, "text", ""))
            for block in (getattr(result, "content", []) or [])
            if getattr(block, "text", None)
        )

    def query(self, query_name: str, **params: Any) -> Any:
        return self.call_tool(
            "tigergraph__run_installed_query",
            {"query_name": query_name, "params": params, "graph_name": self.graph_name},
        )

    def close(self) -> None:
        if not self._thread.is_alive() or self._stop is None:
            return
        self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(timeout=10)
