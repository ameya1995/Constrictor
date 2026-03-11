"""Tests for the MCP server -- constrictor_* tool handlers."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from constrictor.core.models import ScanOptions
from constrictor.core.orchestrator import run_scan
from constrictor.export.json_export import export_json
from constrictor.mcp.server import (
    _dispatch,
    _error_text,
    _tool_audit,
    _tool_dependents,
    _tool_impact,
    _tool_paths,
    _tool_rescan_graph,
    _tool_scan,
    _tool_summary,
    create_server,
)
from constrictor.mcp.tools import get_tool_definitions

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "simple_project"


# ── Helpers ───────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def graph_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build a graph from simple_project and write it to a temp file."""
    out = tmp_path_factory.mktemp("mcp") / "graph.json"
    options = ScanOptions(root_path=FIXTURE_DIR)
    document = run_scan(options)
    export_json(document, out)
    return out


# ── Tool definitions ──────────────────────────────────────────────────────────


def test_tool_definitions_count() -> None:
    tools = get_tool_definitions()
    assert len(tools) == 13


def test_tool_names() -> None:
    names = {t.name for t in get_tool_definitions()}
    expected = {
        "constrictor_scan",
        "constrictor_impact",
        "constrictor_paths",
        "constrictor_audit",
        "constrictor_dependents",
        "constrictor_summary",
        "constrictor_search",
        "constrictor_file_context",
        "constrictor_diff_impact",
        "constrictor_unused",
        "constrictor_batch_impact",
        "constrictor_cycles",
        "constrictor_rescan_graph",
    }
    assert names == expected


def test_tool_definitions_have_descriptions() -> None:
    for tool in get_tool_definitions():
        assert tool.description, f"Tool {tool.name} has no description"


def test_tool_definitions_have_input_schemas() -> None:
    for tool in get_tool_definitions():
        assert tool.inputSchema, f"Tool {tool.name} has no inputSchema"
        assert tool.inputSchema.get("type") == "object"


# ── Server creation ───────────────────────────────────────────────────────────


def test_create_server_returns_server() -> None:
    from mcp.server import Server

    server = create_server()
    assert isinstance(server, Server)


# ── constrictor_scan ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_basic() -> None:
    result = await _tool_scan({"project_path": str(FIXTURE_DIR)})
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "statistics" in data
    assert "summary" in data
    assert data["statistics"]["total_nodes"] > 0


@pytest.mark.asyncio
async def test_scan_writes_output_file(tmp_path: Path) -> None:
    out = tmp_path / "graph.json"
    result = await _tool_scan({"project_path": str(FIXTURE_DIR), "output_path": str(out)})
    data = json.loads(result[0].text)
    assert data["graph_written_to"] == str(out)
    assert out.exists()


@pytest.mark.asyncio
async def test_scan_missing_project_path() -> None:
    result = await _tool_scan({})
    assert result[0].text.startswith("ERROR:")


@pytest.mark.asyncio
async def test_scan_nonexistent_path() -> None:
    result = await _tool_scan({"project_path": "/no/such/directory"})
    assert result[0].text.startswith("ERROR:")


# ── constrictor_impact ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_impact_downstream(graph_file: Path) -> None:
    result = await _tool_impact({"node": "greet"}, str(graph_file))
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "focus_node" in data
    assert "nodes" in data
    assert "edges" in data
    assert data["focus_node"]["display_name"] is not None


@pytest.mark.asyncio
async def test_impact_upstream(graph_file: Path) -> None:
    result = await _tool_impact(
        {"node": "greet", "direction": "upstream"}, str(graph_file)
    )
    data = json.loads(result[0].text)
    assert "focus_node" in data


@pytest.mark.asyncio
async def test_impact_missing_node_arg(graph_file: Path) -> None:
    result = await _tool_impact({}, str(graph_file))
    assert result[0].text.startswith("ERROR:")


@pytest.mark.asyncio
async def test_impact_unknown_node(graph_file: Path) -> None:
    result = await _tool_impact({"node": "zzz_no_such_node_xyz"}, str(graph_file))
    assert result[0].text.startswith("ERROR:")


@pytest.mark.asyncio
async def test_impact_respects_max_depth(graph_file: Path) -> None:
    r1 = await _tool_impact({"node": "greet", "max_depth": 1}, str(graph_file))
    r6 = await _tool_impact({"node": "greet", "max_depth": 6}, str(graph_file))
    d1 = json.loads(r1[0].text)
    d6 = json.loads(r6[0].text)
    # depth 6 should reach at least as many nodes as depth 1
    assert d6["affected_node_count"] >= d1["affected_node_count"]


# ── constrictor_paths ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_paths_basic(graph_file: Path) -> None:
    result = await _tool_paths({"from_node": "app.main", "to_node": "app.utils"}, str(graph_file))
    data = json.loads(result[0].text)
    assert "from_node" in data
    assert "to_node" in data
    assert "paths" in data
    assert "path_count" in data


@pytest.mark.asyncio
async def test_paths_missing_args(graph_file: Path) -> None:
    result = await _tool_paths({"from_node": "app.main"}, str(graph_file))
    assert result[0].text.startswith("ERROR:")


@pytest.mark.asyncio
async def test_paths_unknown_node(graph_file: Path) -> None:
    result = await _tool_paths(
        {"from_node": "zzz_no_such", "to_node": "app.utils"}, str(graph_file)
    )
    assert result[0].text.startswith("ERROR:")


# ── constrictor_audit ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_basic(graph_file: Path) -> None:
    result = await _tool_audit(str(graph_file))
    data = json.loads(result[0].text)
    assert "unresolved_count" in data
    assert "ambiguous_count" in data
    assert "unresolved_edges" in data
    assert "ambiguous_edges" in data


@pytest.mark.asyncio
async def test_audit_missing_file() -> None:
    result = await _tool_audit("/no/such/graph.json")
    assert result[0].text.startswith("ERROR:")


# ── constrictor_dependents ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dependents_basic(graph_file: Path) -> None:
    utils_file = str(FIXTURE_DIR / "app" / "utils.py")
    result = await _tool_dependents({"file_path": utils_file}, str(graph_file))
    data = json.loads(result[0].text)
    assert "file_path" in data
    assert "dependent_count" in data
    assert "dependents" in data


@pytest.mark.asyncio
async def test_dependents_missing_file_arg(graph_file: Path) -> None:
    result = await _tool_dependents({}, str(graph_file))
    assert result[0].text.startswith("ERROR:")


# ── constrictor_summary ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_summary_basic(graph_file: Path) -> None:
    result = await _tool_summary(str(graph_file))
    data = json.loads(result[0].text)
    assert "summary" in data
    assert "statistics" in data
    assert len(data["summary"]) > 10


@pytest.mark.asyncio
async def test_summary_missing_file() -> None:
    result = await _tool_summary("/no/such/graph.json")
    assert result[0].text.startswith("ERROR:")


# ── _dispatch routing ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_unknown_tool(graph_file: Path) -> None:
    result = await _dispatch("constrictor_unknown", {}, str(graph_file), False)
    assert result[0].text.startswith("ERROR:")


@pytest.mark.asyncio
async def test_dispatch_missing_graph_path() -> None:
    result = await _dispatch("constrictor_summary", {}, None, False)
    assert result[0].text.startswith("ERROR:")


@pytest.mark.asyncio
async def test_dispatch_scan_no_graph_needed() -> None:
    result = await _dispatch(
        "constrictor_scan", {"project_path": str(FIXTURE_DIR)}, None, False
    )
    data = json.loads(result[0].text)
    assert "statistics" in data


# ── _error_text helper ────────────────────────────────────────────────────────


def test_error_text_format() -> None:
    result = _error_text("something went wrong")
    assert len(result) == 1
    assert result[0].text == "ERROR: something went wrong"


# ── constrictor_rescan_graph ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rescan_graph_basic(graph_file: Path) -> None:
    result = await _tool_rescan_graph({}, str(graph_file))
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["status"] == "ok"
    assert data["graph_written_to"] == str(graph_file)
    assert data["statistics"]["total_nodes"] > 0
    assert "elapsed_seconds" in data
    assert graph_file.exists()


@pytest.mark.asyncio
async def test_rescan_graph_incremental_flag(graph_file: Path) -> None:
    result = await _tool_rescan_graph({"incremental": False}, str(graph_file))
    data = json.loads(result[0].text)
    assert data["status"] == "ok"
    assert data["statistics"]["total_nodes"] > 0


@pytest.mark.asyncio
async def test_rescan_graph_missing_graph() -> None:
    result = await _tool_rescan_graph({}, "/no/such/graph.json")
    assert result[0].text.startswith("ERROR:")


@pytest.mark.asyncio
async def test_rescan_graph_no_graph_path() -> None:
    result = await _dispatch("constrictor_rescan_graph", {}, None, False)
    assert result[0].text.startswith("ERROR:")
