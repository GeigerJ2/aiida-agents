"""AiiDA Agents MCP Server."""

from __future__ import annotations
from aiida import load_profile
from fastmcp import FastMCP
from aiida_agents.mcp.tools import register_all

try:
    load_profile()
except Exception:  # pragma: no cover
    pass

mcp = FastMCP(
    "aiida-agents",
    instructions="Tools for exploring an AiiDA database using natural language.",
)
register_all(mcp)


def main() -> None:  # pragma: no cover
    """Run the MCP server."""
    mcp.run(transport="streamable-http", port=8000)


if __name__ == "__main__":  # pragma: no cover
    main()
