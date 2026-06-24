"""Lightweight sync MCP client for calling the agentr-tools MCP server.

Shared by agent/nodes.py and api/main.py in fraud-config-agent-v2.
"""
from __future__ import annotations

import json
import os

import httpx


class MCPClient:
    def __init__(self, base_url: str) -> None:
        endpoint = base_url.rstrip("/")
        self._url = f"{endpoint}/mcp"
        self._http = httpx.Client(timeout=60)
        self._id = 0
        self._session_id: str | None = None

    def _initialize(self) -> None:
        self._id += 1
        resp = self._http.post(
            self._url,
            json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "agentr-agent", "version": "1.0"},
                },
                "id": self._id,
            },
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        )
        resp.raise_for_status()
        self._session_id = resp.headers.get("mcp-session-id")

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self._session_id:
            h["mcp-session-id"] = self._session_id
        return h

    def call(self, tool_name: str, **kwargs) -> dict:
        if self._session_id is None:
            try:
                self._initialize()
            except Exception as e:
                return {"error": f"MCP init failed: {e}"}

        self._id += 1
        try:
            resp = self._http.post(
                self._url,
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": kwargs},
                    "id": self._id,
                },
                headers=self._headers(),
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            return {"error": f"MCP HTTP {e.response.status_code}: {e.response.text[:200]}"}
        except Exception as e:
            return {"error": f"MCP request failed: {e}"}

        return _parse_response(resp)

    def close(self) -> None:
        self._http.close()


def _parse_response(resp: httpx.Response) -> dict:
    ct = resp.headers.get("content-type", "")
    if "text/event-stream" in ct:
        data = _parse_sse(resp.content)
    else:
        try:
            data = resp.json()
        except Exception:
            data = _parse_sse(resp.content)

    if "error" in data:
        err = data["error"]
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        return {"error": msg}

    content = (data.get("result") or {}).get("content") or []
    if content and content[0].get("type") == "text":
        text = content[0]["text"]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"result": text}
    return {"error": "unexpected MCP response format", "raw": data}


def _parse_sse(body: bytes) -> dict:
    for line in body.decode(errors="replace").splitlines():
        if line.startswith("data:"):
            try:
                return json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
    return {"error": "no parseable SSE data found"}


_client: MCPClient | None = None


def _get() -> MCPClient:
    global _client
    if _client is None:
        url = os.environ.get("MCP_SERVER_URL", "http://localhost:8000")
        _client = MCPClient(url)
    return _client


def call_tool(name: str, **kwargs) -> dict:
    """Call an MCP tool by name with keyword arguments."""
    return _get().call(name, **kwargs)
