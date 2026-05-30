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

logger = logging.getLogger(__name__)


def get_process_status(pk: int) -> dict[str, str | int | None]:
    """Get the status and exit code of an AiiDA process by its primary key."""
    logger.debug("get_process_status(pk=%d)", pk)
    try:
        node_service: NodeService[orm.Node, t.Any] = NodeService(orm.Node)
        # Load the base node info
        node_info = node_service.get_one(pk)
        # Load attributes fields
        attrs: dict[str, t.Any] = node_service.get_field(pk, "attributes") or {}
        res = {
            "pk": node_info.get("pk"),
            "process_label": attrs.get("process_label"),
            "process_type": node_info.get("process_type"),
            "state": attrs.get("process_state"),
            "exit_status": attrs.get("exit_status"),
            "exit_message": attrs.get("exit_message"),
        }
        logger.debug("Tool output: %s", res)
        return res
    except (NotExistent, ValueError) as exc:
        raise ToolError(f"No process node found with pk={pk}. Try list_processes() to see recent ones.") from exc


def list_processes(limit: int = 10) -> list[dict[str, str | int | None]]:
    """List recent AiiDA processes, newest first."""
    logger.debug("list_processes(limit=%d)", limit)
    node_service: NodeService[orm.Node, t.Any] = NodeService(orm.Node)
    params = QueryBuilderParams(
        page_size=limit,
        filters={"node_type": {"like": "%process%"}},
        order_by={"ctime": "desc"},
    )
    res = node_service.get_many(params)
    records = []
    for item in res.data:
        pk = item.get("pk")
        if pk is None:
            continue
        # Pull process details from attributes if possible
        attrs: dict[str, t.Any] = {}
        try:
            attrs = node_service.get_field(pk, "attributes") or {}
        except Exception:
            pass
        records.append(
            {
                "pk": pk,
                "uuid": item.get("uuid"),
                "node_type": item.get("node_type"),
                "process_type": item.get("process_type"),
                "state": attrs.get("process_state"),
                "exit_status": attrs.get("exit_status"),
            }
        )
    logger.debug("Tool output: Returned %d process records.", len(records))
    return records


def register(mcp: FastMCP) -> None:
    """Register process tools on the MCP server."""
    mcp.tool()(get_process_status)
    mcp.tool()(list_processes)
