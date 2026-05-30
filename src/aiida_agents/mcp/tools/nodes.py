"""MCP tools for AiiDA generic node queries."""

from __future__ import annotations
import typing as t
from functools import lru_cache
from aiida import orm
from aiida.plugins.entry_point import get_entry_point_names, load_entry_point
from fastmcp import FastMCP
from aiida_restapi.services.node import NodeService
from aiida_restapi.common.query import QueryBuilderParams
from .._types import Identifier

# Abstract hierarchy levels (AiiDA's non-concrete Node base classes): these are
# ``node_type`` *prefixes*, not entry points, so they can't be derived from the
# registry. ``like "<prefix>%"`` selects the whole subtree (e.g. ``process.%`` is
# every process node). Both the short name and the ``...Node`` class name are
# accepted, since this is the forgiving, agent-facing input layer.
_SUBTREE_PREFIXES: dict[str, str] = {
    "node": "%",
    "data": "data.%",
    "process": "process.%",
    "processnode": "process.%",
    "calculation": "process.calculation.%",
    "calculationnode": "process.calculation.%",
    "workflow": "process.workflow.%",
    "workflownode": "process.workflow.%",
}


@lru_cache(maxsize=1)
def _node_type_index() -> dict[str, str]:
    """Lowercased class name and entry-point name -> node_type, from the registry."""
    index: dict[str, str] = {}
    for group in ("aiida.data", "aiida.node"):
        for name in get_entry_point_names(group):
            try:
                cls = load_entry_point(group, name)
            except Exception:
                continue
            if node_type := getattr(cls, "class_node_type", None):
                index[name.lower()] = node_type  # e.g. "core.structure"
                index[cls.__name__.lower()] = node_type  # e.g. "structuredata"
    return index


def _node_type_for(name: str) -> str | None:
    """Resolve a class/entry-point name (or a raw node_type) to a node_type string."""
    if name.endswith("."):  # already a node_type, e.g. "data.core.int.Int."
        return name
    return _node_type_index().get(name.lower())


def query_nodes(
    node_type: str = "process",
    limit: int = 10,
) -> list[dict[str, t.Any]]:
    """Query AiiDA nodes by type.

    ``node_type`` accepts an abstract hierarchy level (``node``, ``data``,
    ``process``, ``calculation``, ``workflow``, or their ``...Node`` class
    names) which matches the whole subtree, a concrete class or entry-point name
    (``StructureData``, ``Int``, ``CalcJobNode``, ...) resolved to an exact
    ``node_type`` via the plugin registry, or, as a last resort, an arbitrary
    substring of the ``node_type``.
    """
    print(
        f"\n🔍 [Agent invoking tool] query_nodes(node_type='{node_type}', limit={limit})..."
    )

    normalized = node_type.lower()
    filters: dict[str, t.Any]
    if normalized in _SUBTREE_PREFIXES:
        filters = {"node_type": {"like": _SUBTREE_PREFIXES[normalized]}}
    elif (node_type_string := _node_type_for(node_type)) is not None:
        filters = {"node_type": node_type_string}  # exact, resolved from entry points
    else:
        filters = {"node_type": {"like": f"%{node_type}%"}}  # last-resort substring

    try:
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
        print(f"✅ Tool output: Returned {len(records)} nodes.")
        return records
    except Exception as e:
        print(f"❌ Tool error: {e}")
        return [{"error": str(e)}]


def get_node_inputs(identifier: Identifier) -> list[dict[str, t.Any]]:
    """Get all input nodes of an AiiDA node by its pk or uuid."""
    print(f"\n🔍 [Agent invoking tool] get_node_inputs(identifier={identifier})...")
    try:
        # Single-node traversal: plain ORM gives the linked nodes directly.
        node = orm.load_node(identifier)
        results = [
            {
                "pk": entry.node.pk,
                "uuid": entry.node.uuid,
                "node_type": entry.node.node_type,
                "link_label": entry.link_label,
                "link_type": entry.link_type.value,
            }
            for entry in node.base.links.get_incoming().all()
        ]
        print(f"✅ Tool output: Found {len(results)} incoming links.")
        return results
    except Exception as e:
        print(f"❌ Tool error: {e}")
        return [{"error": str(e)}]


def get_node_outputs(identifier: Identifier) -> list[dict[str, t.Any]]:
    """Get all output nodes of an AiiDA node by its pk or uuid."""
    print(f"\n🔍 [Agent invoking tool] get_node_outputs(identifier={identifier})...")
    try:
        # Single-node traversal: plain ORM gives the linked nodes directly.
        node = orm.load_node(identifier)
        results = [
            {
                "pk": entry.node.pk,
                "uuid": entry.node.uuid,
                "node_type": entry.node.node_type,
                "link_label": entry.link_label,
                "link_type": entry.link_type.value,
            }
            for entry in node.base.links.get_outgoing().all()
        ]
        print(f"✅ Tool output: Found {len(results)} outgoing links.")
        return results
    except Exception as e:
        print(f"❌ Tool error: {e}")
        return [{"error": str(e)}]


def register(mcp: FastMCP) -> None:
    """Register node tools on the MCP server."""
    mcp.tool()(query_nodes)
    mcp.tool()(get_node_inputs)
    mcp.tool()(get_node_outputs)
