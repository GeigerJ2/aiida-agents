"""AiiDA Agents MCP Server."""

from __future__ import annotations

import logging
import os
import sys

from aiida import load_profile
from fastmcp import FastMCP
from aiida_agents.mcp.tools import register_all

logging.basicConfig(
    level=os.getenv("AIIDA_AGENTS_LOG_LEVEL", "INFO"), stream=sys.stderr
)


def get_mcp() -> FastMCP:
    """Build the MCP server and register its tools. No profile needed here."""
    mcp = FastMCP(
        "aiida-agents",
        instructions="Tools for exploring an AiiDA database using natural language.",
    )
    register_all(mcp)
    return mcp


mcp = get_mcp()


def main() -> None:  # pragma: no cover
    """Load the profile and run the MCP server."""
    load_profile()
    mcp.run(transport="streamable-http", port=8000)


if __name__ == "__main__":  # pragma: no cover
    main()
