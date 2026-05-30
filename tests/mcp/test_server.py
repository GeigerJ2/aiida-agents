"""Tests for ``aiida_agents.mcp.server``."""

from __future__ import annotations

import asyncio

from aiida_agents.mcp.server import mcp


def test_tools_registered() -> None:
    """Every tool is wired onto the shared FastMCP instance by ``register_all``."""
    registered = asyncio.run(mcp.get_tools())
    expected = {
        "get_process_status",
        "list_processes",
        "query_nodes",
        "get_node_inputs",
        "get_node_outputs",
        "search_structures",
    }
    assert expected.issubset(registered)
