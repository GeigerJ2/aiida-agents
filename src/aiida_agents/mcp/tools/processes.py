"""MCP tools for AiiDA process nodes."""

from __future__ import annotations

import logging
import typing as t

from aiida import orm
from aiida.common.exceptions import NotExistent
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from aiida_restapi.services.node import NodeService
from aiida_restapi.common.query import QueryBuilderParams

from .._types import Identifier

logger = logging.getLogger(__name__)

_node_service: NodeService[orm.Node, t.Any] = NodeService(orm.Node)


def get_process_status(identifier: Identifier) -> dict[str, str | int | None]:
    """Get the status and exit code of an AiiDA process by its pk or uuid."""
    logger.debug("get_process_status(identifier=%r)", identifier)
    try:
        node = orm.load_node(identifier)
    except NotExistent as exc:
        raise ToolError(
            f"No process found with identifier={identifier}. "
            "Try list_processes() to see recent ones."
        ) from exc

    return {
        "pk": node.pk,
        "process_label": node.process_label,
        "process_type": node.process_type,
        "state": node.process_state.value if node.process_state else None,
        "exit_status": node.exit_status,
        "exit_message": node.exit_message,
    }


def list_processes(limit: int = 10) -> list[dict[str, str | int | None]]:
    """List recent AiiDA processes, newest first."""
    logger.debug("list_processes(limit=%d)", limit)

    params = QueryBuilderParams(
        page_size=limit,
        filters={"node_type": {"like": "%process%"}},
        order_by={"ctime": "desc"},
    )
    res = _node_service.get_many(params)

    records = []
    for item in res.data:
        uuid = item.get("uuid")
        if uuid is None:
            continue

        # Fetch process state and exit status from the node's attributes.
        attrs: dict[str, t.Any] = {}
        try:
            attrs = _node_service.get_field(uuid, "attributes") or {}
        except Exception:
            pass

        records.append(
            {
                "pk": item.get("pk"),
                "uuid": uuid,
                "node_type": item.get("node_type"),
                "process_type": item.get("process_type"),
                "state": attrs.get("process_state"),
                "exit_status": attrs.get("exit_status"),
            }
        )

    logger.debug("list_processes: returned %d records", len(records))
    return records


def register(mcp: FastMCP) -> None:
    """Register process tools on the MCP server."""
    mcp.tool()(get_process_status)
    mcp.tool()(list_processes)
