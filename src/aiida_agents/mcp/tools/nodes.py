"""MCP tools for AiiDA generic node queries."""

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


def query_nodes(
    node_type: str = "ProcessNode",
    limit: int = 10,
) -> list[dict[str, t.Any]]:
    """Query AiiDA nodes by type."""
    logger.debug("query_nodes(node_type=%r, limit=%d)", node_type, limit)

    # Standard common maps for direct, fast, indexed queries
    type_map: dict[str, str] = {
        "processnode": "process.calculation.calcjob.CalcJobNode.",
        "structuredata": "data.core.structure.StructureData.",
        "structure": "data.core.structure.StructureData.",
        "dict": "data.core.dict.Dict.",
        "calcjobnode": "process.calculation.calcjob.CalcJobNode.",
        "calcjob": "process.calculation.calcjob.CalcJobNode.",
        "pwcalculation": "process.calculation.calcjob.CalcJobNode.",
        "calculation": "process.calculation.calcjob.CalcJobNode.",
        "workchainnode": "process.workflow.workchain.WorkChainNode.",
        "workchain": "process.workflow.workchain.WorkChainNode.",
        "pwbaseworkchain": "process.workflow.workchain.WorkChainNode.",
    }

    normalized_type = node_type.lower()

    if normalized_type in type_map:
        filter_type = type_map[normalized_type]
        filters = {"node_type": {"like": f"{filter_type}%"}}
    else:
        filters = {"node_type": {"like": f"%{node_type}%"}}

    node_service: NodeService[orm.Node, t.Any] = NodeService(orm.Node)
    params = QueryBuilderParams(
        page_size=limit, filters=filters, order_by={"ctime": "desc"}
    )
    res = node_service.get_many(params)
    records = [
        {
            "pk": item.get("pk"),
            "uuid": item.get("uuid"),
            "node_type": item.get("node_type"),
            "created": str(item.get("ctime")),
        }
        for item in res.data
    ]
    logger.debug("Tool output: Returned %d nodes.", len(records))
    return records


def get_node_inputs(pk: int) -> list[dict[str, t.Any]]:
    """Get all input nodes of an AiiDA node by its primary key."""
    logger.debug("get_node_inputs(pk=%d)", pk)
    try:
        node_service: NodeService[orm.Node, t.Any] = NodeService(orm.Node)
        # Resolve PK to UUID for NodeService compatibility
        node_info = node_service.get_one(pk)
    except (NotExistent, ValueError) as exc:
        raise ToolError(f"No node found with pk={pk}. Try query_nodes() to see available ones.") from exc

    uuid = node_info.get("uuid")
    if not uuid:
        raise ToolError(f"Could not resolve UUID for PK {pk}")

    # Load incoming links using REST api NodeService
    params = QueryBuilderParams(page_size=100)
    res = node_service.get_links(
        uuid=uuid, direction="incoming", query_params=params
    )

    results = []
    for entry in res.data:
        # Resolve the source node details to get its PK and node_type
        source_uuid = entry.get("source")
        if not source_uuid:
            continue
        try:
            source_info = node_service.get_one(source_uuid)
            source_pk = source_info.get("pk")
            source_type = source_info.get("node_type")
        except Exception:
            source_pk = None
            source_type = "Unknown"

        results.append(
            {
                "pk": source_pk,
                "uuid": source_uuid,
                "node_type": source_type,
                "link_label": entry.get("link_label"),
                "link_type": entry.get("link_type"),
            }
        )
    logger.debug("Tool output: Found %d incoming links.", len(results))
    return results


def get_node_outputs(pk: int) -> list[dict[str, t.Any]]:
    """Get all output nodes of an AiiDA node by its primary key."""
    logger.debug("get_node_outputs(pk=%d)", pk)
    try:
        node_service: NodeService[orm.Node, t.Any] = NodeService(orm.Node)
        # Resolve PK to UUID
        node_info = node_service.get_one(pk)
    except (NotExistent, ValueError) as exc:
        raise ToolError(f"No node found with pk={pk}. Try query_nodes() to see available ones.") from exc

    uuid = node_info.get("uuid")
    if not uuid:
        raise ToolError(f"Could not resolve UUID for PK {pk}")

    # Load outgoing links using REST api NodeService
    params = QueryBuilderParams(page_size=100)
    res = node_service.get_links(
        uuid=uuid, direction="outgoing", query_params=params
    )

    results = []
    for entry in res.data:
        # Resolve the target node details to get its PK and node_type
        target_uuid = entry.get("target")
        if not target_uuid:
            continue
        try:
            target_info = node_service.get_one(target_uuid)
            target_pk = target_info.get("pk")
            target_type = target_info.get("node_type")
        except Exception:
            target_pk = None
            target_type = "Unknown"

        results.append(
            {
                "pk": target_pk,
                "uuid": target_uuid,
                "node_type": target_type,
                "link_label": entry.get("link_label"),
                "link_type": entry.get("link_type"),
            }
        )
    logger.debug("Tool output: Found %d outgoing links.", len(results))
    return results


def register(mcp: FastMCP) -> None:
    """Register node tools on the MCP server."""
    mcp.tool()(query_nodes)
    mcp.tool()(get_node_inputs)
    mcp.tool()(get_node_outputs)
