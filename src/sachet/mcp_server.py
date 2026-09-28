"""Optional MCP server: lets Claude Desktop, Cursor or any MCP client call Sachet as a tool."""

from __future__ import annotations

import sys

from .planner import Agent
from .report import to_markdown


def verify_job_offer(text: str, budget: int = 6) -> str:
    """Investigate a job or internship offer with live SerpApi searches.

    Returns a markdown report with a verdict, a 0-100 risk score, findings and cited sources.
    `budget` caps the number of live SerpApi searches for this call.
    """
    return to_markdown(Agent().run(text, budget=max(1, min(int(budget), 12))))


def _server_class():
    try:  # mcp 2.x
        from mcp.server.mcpserver import MCPServer

        return MCPServer
    except ImportError:
        pass
    try:  # mcp 1.x
        from mcp.server.fastmcp import FastMCP

        return FastMCP
    except ImportError:
        return None


def build_server():
    cls = _server_class()
    if cls is None:
        return None
    server = cls("Sachet")
    server.tool()(verify_job_offer)
    return server


def main():
    server = build_server()
    if server is None:
        print('MCP is unavailable. Install with: pip install "sachet[mcp]"', file=sys.stderr)
        return 1
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
