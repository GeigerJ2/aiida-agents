"""Tests for AiiDA Agents MCP tools."""

from __future__ import annotations
from unittest.mock import MagicMock, patch

from aiida_agents.mcp.server import mcp
from aiida_agents.mcp.tools.processes import get_process_status, list_processes
from aiida_agents.mcp.tools.nodes import query_nodes, get_node_inputs, get_node_outputs
from aiida_agents.mcp.tools.structures import search_structures


def test_mcp_registration() -> None:
    """Verify that all tools are successfully registered on the FastMCP instance."""
    registered_tools = set(mcp._tool_manager._tools.keys())
    expected_tools = {
        "get_process_status",
        "list_processes",
        "query_nodes",
        "get_node_inputs",
        "get_node_outputs",
        "search_structures",
    }
    assert expected_tools.issubset(registered_tools)


@patch("aiida_agents.mcp.tools.processes.orm.load_node")
def test_get_process_status_success(mock_load_node: MagicMock) -> None:
    """Test get_process_status tool logic on a successful node lookup."""
    mock_node = MagicMock()
    mock_node.pk = 42
    mock_node.process_label = "ArithmeticAddCalculation"
    mock_node.process_type = "aiida.calculations:arithmetic.add"
    mock_node.process_state = "Finished"
    mock_node.exit_status = 0
    mock_node.exit_message = "Completed successfully"
    mock_load_node.return_value = mock_node

    result = get_process_status(42)

    assert result["pk"] == 42
    assert result["process_label"] == "ArithmeticAddCalculation"
    assert result["state"] == "Finished"
    assert result["exit_status"] == 0
    assert result["exit_message"] == "Completed successfully"
    mock_load_node.assert_called_once_with(pk=42)


@patch("aiida_agents.mcp.tools.processes.orm.load_node")
def test_get_process_status_error(mock_load_node: MagicMock) -> None:
    """Test get_process_status tool logic handles exceptions gracefully."""
    mock_load_node.side_effect = ValueError("Node with pk 999 does not exist")

    result = get_process_status(999)

    assert "error" in result
    assert "Node with pk 999 does not exist" in str(result["error"])


@patch("aiida_agents.mcp.tools.processes.orm.QueryBuilder")
def test_list_processes(mock_qb_class: MagicMock) -> None:
    """Test list_processes tool successfully queries and formats process entries."""
    mock_qb = MagicMock()
    mock_qb_class.return_value = mock_qb
    mock_qb.all.return_value = [
        [
            10,
            "uuid-10",
            "node.process.calc.job.CalcJobNode.",
            "some_type",
            "finished",
            0,
        ],
        [
            9,
            "uuid-9",
            "node.process.workflow.workchain.WorkChainNode.",
            "some_type",
            "running",
            None,
        ],
    ]

    result = list_processes(limit=2)

    assert len(result) == 2
    assert result[0]["pk"] == 10
    assert result[0]["state"] == "finished"
    assert result[0]["exit_status"] == 0
    assert result[1]["pk"] == 9
    assert result[1]["state"] == "running"
    assert result[1]["exit_status"] is None


@patch("aiida_agents.mcp.tools.nodes.orm.QueryBuilder")
def test_query_nodes(mock_qb_class: MagicMock) -> None:
    """Test query_nodes tool successfully queries generic nodes and returns results."""
    mock_qb = MagicMock()
    mock_qb_class.return_value = mock_qb
    mock_qb.all.return_value = [
        [42, "uuid-42", "node.data.dict.Dict.", "2026-05-27 12:00:00"],
    ]

    result = query_nodes(node_type="Dict", limit=1)

    assert len(result) == 1
    assert result[0]["pk"] == 42
    assert result[0]["node_type"] == "node.data.dict.Dict."
    assert result[0]["created"] == "2026-05-27 12:00:00"


@patch("aiida_agents.mcp.tools.nodes.orm.load_node")
def test_get_node_inputs(mock_load_node: MagicMock) -> None:
    """Test get_node_inputs tool successfully retrieves incoming links of a node."""
    mock_node = MagicMock()
    mock_link_entry = MagicMock()
    mock_link_entry.node.pk = 5
    mock_link_entry.node.uuid = "uuid-5"
    mock_link_entry.node.node_type = "node.data.int.Int."
    mock_link_entry.link_label = "x"
    mock_link_entry.link_type = "input"

    mock_node.base.links.get_incoming.return_value.all.return_value = [mock_link_entry]
    mock_load_node.return_value = mock_node

    result = get_node_inputs(10)

    assert len(result) == 1
    assert result[0]["pk"] == 5
    assert result[0]["link_label"] == "x"
    assert result[0]["link_type"] == "input"


@patch("aiida_agents.mcp.tools.nodes.orm.load_node")
def test_get_node_outputs(mock_load_node: MagicMock) -> None:
    """Test get_node_outputs tool successfully retrieves outgoing links of a node."""
    mock_node = MagicMock()
    mock_link_entry = MagicMock()
    mock_link_entry.node.pk = 12
    mock_link_entry.node.uuid = "uuid-12"
    mock_link_entry.node.node_type = "node.data.float.Float."
    mock_link_entry.link_label = "result"
    mock_link_entry.link_type = "output"

    mock_node.base.links.get_outgoing.return_value.all.return_value = [mock_link_entry]
    mock_load_node.return_value = mock_node

    result = get_node_outputs(10)

    assert len(result) == 1
    assert result[0]["pk"] == 12
    assert result[0]["link_label"] == "result"
    assert result[0]["link_type"] == "output"


@patch("aiida_agents.mcp.tools.structures.orm.load_node")
@patch("aiida_agents.mcp.tools.structures.orm.QueryBuilder")
def test_search_structures(mock_qb_class: MagicMock, mock_load_node: MagicMock) -> None:
    """Test search_structures tool successfully searches structure data with/without formula filter."""
    mock_qb = MagicMock()
    mock_qb_class.return_value = mock_qb
    # Query builder returns structure nodes
    mock_qb.all.return_value = [[20, "uuid-20", "2026-05-27 12:00:00"]]

    mock_structure_node = MagicMock()
    mock_structure_node.get_formula.return_value = "Fe2O3"
    mock_structure_node.sites = [
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    ]
    mock_load_node.return_value = mock_structure_node

    # 1. Search with matching formula
    result_match = search_structures(formula="Fe", limit=1)
    assert len(result_match) == 1
    assert result_match[0]["pk"] == 20
    assert result_match[0]["formula"] == "Fe2O3"
    assert result_match[0]["num_sites"] == 5

    # 2. Search with non-matching formula
    result_no_match = search_structures(formula="Si", limit=1)
    assert len(result_no_match) == 0
