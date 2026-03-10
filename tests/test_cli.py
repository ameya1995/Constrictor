from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from constrictor.cli.main import app
from constrictor.core.models import Certainty
from constrictor.export.json_export import export_json
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.models import EdgeType, NodeType

runner = CliRunner()

FIXTURE_PROJECT = Path(__file__).parent / "fixtures" / "simple_project"


def _make_graph_file(tmp_path: Path) -> Path:
    """Build a small known graph and write it to a temp JSON file."""
    builder = GraphBuilder()
    builder.add_node(
        "mod:a", NodeType.MODULE, "app.main",
        qualified_name="app.main", display_name="app.main",
        file_path="app/main.py",
    )
    builder.add_node(
        "mod:b", NodeType.MODULE, "app.utils",
        qualified_name="app.utils", display_name="app.utils",
        file_path="app/utils.py",
    )
    builder.add_node(
        "func:greet", NodeType.FUNCTION, "greet",
        qualified_name="app.utils::greet", display_name="app.utils::greet",
        file_path="app/utils.py",
    )
    builder.add_node(
        "func:run_app", NodeType.FUNCTION, "run_app",
        qualified_name="app.main::run_app", display_name="app.main::run_app",
        file_path="app/main.py",
    )
    builder.add_edge("mod:a", "mod:b", EdgeType.IMPORTS, "main -> utils")
    builder.add_edge("func:run_app", "func:greet", EdgeType.CALLS, "run_app -> greet")
    builder.add_edge(
        "mod:a", "mod:b", EdgeType.IMPORTS_FROM, "main ambiguous import",
        certainty=Certainty.AMBIGUOUS,
    )

    doc = builder.build()
    graph_path = tmp_path / "graph.json"
    export_json(doc, graph_path)
    return graph_path


class TestScanCommand:
    def test_scan_simple_project(self) -> None:
        result = runner.invoke(app, ["scan", str(FIXTURE_PROJECT)])
        assert result.exit_code == 0
        assert "Python file" in result.output

    def test_scan_writes_output_file(self, tmp_path: Path) -> None:
        out = tmp_path / "out.json"
        result = runner.invoke(app, ["scan", str(FIXTURE_PROJECT), "-o", str(out)])
        assert result.exit_code == 0
        assert out.exists()
        data = json.loads(out.read_text())
        assert "nodes" in data
        assert "edges" in data

    def test_scan_verbose(self) -> None:
        result = runner.invoke(app, ["scan", str(FIXTURE_PROJECT), "--verbose"])
        assert result.exit_code == 0
        assert "Scanning" in result.output

    def test_scan_invalid_path_exits_nonzero(self) -> None:
        result = runner.invoke(app, ["scan", "/nonexistent_path_xyz"])
        assert result.exit_code != 0


class TestImpactCommand:
    def test_impact_downstream(self, tmp_path: Path) -> None:
        graph_path = _make_graph_file(tmp_path)
        result = runner.invoke(app, ["impact", "--node", "mod:a", "--graph", str(graph_path)])
        assert result.exit_code == 0
        assert "app.utils" in result.output or "mod:b" in result.output

    def test_impact_upstream(self, tmp_path: Path) -> None:
        graph_path = _make_graph_file(tmp_path)
        result = runner.invoke(
            app,
            ["impact", "--node", "func:greet", "--graph", str(graph_path), "--direction", "upstream"],
        )
        assert result.exit_code == 0
        assert "run_app" in result.output

    def test_impact_unknown_node_exits_nonzero(self, tmp_path: Path) -> None:
        graph_path = _make_graph_file(tmp_path)
        result = runner.invoke(
            app, ["impact", "--node", "nonexistent_xyz_123", "--graph", str(graph_path)]
        )
        assert result.exit_code == 1

    def test_impact_invalid_direction_exits_nonzero(self, tmp_path: Path) -> None:
        graph_path = _make_graph_file(tmp_path)
        result = runner.invoke(
            app,
            ["impact", "--node", "mod:a", "--graph", str(graph_path), "--direction", "sideways"],
        )
        assert result.exit_code == 2

    def test_impact_leaf_shows_output(self, tmp_path: Path) -> None:
        # mod:b has no upstream importers (nothing imports mod:b in the test graph... wait,
        # mod:a imports mod:b so mod:b does have upstream. Use a node with no incoming edges.
        # func:greet has func:run_app calling it, so use mod:a upstream -- it has no importers.
        graph_path = _make_graph_file(tmp_path)
        result = runner.invoke(app, ["impact", "--node", "mod:a", "--graph", str(graph_path), "--direction", "upstream"])
        assert result.exit_code == 0
        assert "No affected nodes" in result.output


class TestPathsCommand:
    def test_paths_between_known_nodes(self, tmp_path: Path) -> None:
        graph_path = _make_graph_file(tmp_path)
        # mod:a --[IMPORTS]--> mod:b, so there is a direct 1-hop path
        result = runner.invoke(
            app,
            ["paths", "--from", "mod:a", "--to", "mod:b", "--graph", str(graph_path)],
        )
        assert result.exit_code == 0
        assert "Path 1" in result.output

    def test_paths_no_path(self, tmp_path: Path) -> None:
        graph_path = _make_graph_file(tmp_path)
        result = runner.invoke(
            app,
            ["paths", "--from", "func:greet", "--to", "mod:a", "--graph", str(graph_path)],
        )
        assert result.exit_code == 0
        assert "No paths found" in result.output

    def test_paths_unknown_node_exits_nonzero(self, tmp_path: Path) -> None:
        graph_path = _make_graph_file(tmp_path)
        result = runner.invoke(
            app,
            ["paths", "--from", "mod:a", "--to", "nonexistent_xyz", "--graph", str(graph_path)],
        )
        assert result.exit_code == 1


class TestAuditCommand:
    def test_audit_shows_ambiguous(self, tmp_path: Path) -> None:
        graph_path = _make_graph_file(tmp_path)
        result = runner.invoke(app, ["audit", "--graph", str(graph_path)])
        assert result.exit_code == 0
        assert "Ambiguous" in result.output

    def test_audit_clean_graph_reports_none(self, tmp_path: Path) -> None:
        builder = GraphBuilder()
        builder.add_node("mod:x", NodeType.MODULE, "x", qualified_name="x", display_name="x")
        builder.add_node("mod:y", NodeType.MODULE, "y", qualified_name="y", display_name="y")
        builder.add_edge("mod:x", "mod:y", EdgeType.IMPORTS, "x -> y")
        doc = builder.build()
        graph_path = tmp_path / "clean.json"
        export_json(doc, graph_path)

        result = runner.invoke(app, ["audit", "--graph", str(graph_path)])
        assert result.exit_code == 0
        assert "No ambiguous" in result.output


class TestSummaryCommand:
    def test_summary_output(self, tmp_path: Path) -> None:
        graph_path = _make_graph_file(tmp_path)
        result = runner.invoke(app, ["summary", "--graph", str(graph_path)])
        assert result.exit_code == 0
        assert "nodes" in result.output.lower() or "edge" in result.output.lower()

    def test_summary_from_scanned_project(self, tmp_path: Path) -> None:
        out = tmp_path / "graph.json"
        runner.invoke(app, ["scan", str(FIXTURE_PROJECT), "-o", str(out)])
        result = runner.invoke(app, ["summary", "--graph", str(out)])
        assert result.exit_code == 0
        assert len(result.output) > 0
