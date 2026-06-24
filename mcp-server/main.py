"""AgentR MCP Server — centralized tool management for fraud detection agents.

Exposes all tools via MCP HTTP/SSE (streamable-http) transport so both
fraud-analysis-agent and fraud-config-agent-v2 can call them as MCP clients.

Run:
    python main.py
or:
    uvicorn main:mcp.get_asgi_app() --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()


def create_app() -> FastMCP:
    mcp = FastMCP("agentr-tools")

    from tools.shared import register as reg_shared
    from tools.investigation import register as reg_investigation
    from tools.config import register as reg_config

    reg_shared(mcp)
    reg_investigation(mcp)
    reg_config(mcp)

    return mcp


mcp = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("MCP_SERVER_PORT", "8000"))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
