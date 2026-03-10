"""Error handling audit tests.

Verifies that:
- CLI commands return the correct exit codes (0 = success, 1 = error, 2 = bad input)
- Missing / corrupt graph files produce useful error messages
- --verbose flag produces timing and debug output
- File I/O failures are caught and reported cleanly
- All CLI commands handle edge cases without Python tracebacks
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from constrictor.cli.main import app
from constrictor.export.json_export import export_json, load_json
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.models import EdgeType, NodeType

runner = CliRunner()

FIXTURE_PROJECT = Path(__file__).parent / "fixtures" / "simple_project"


def _make_graph_file(tmp_path: Path) -> Path:
    builder = GraphBuilder()
    builder.add_node(
        "mod:a", NodeType.MODULE, "app.main",
        qualified_name="app.main", display_name="app.main",
        file_path="app/main.py",
    )
    builder.add_node(
        "func:greet", NodeType.FUNCTION, "greet",
        qualified_name="app.utils::greet", display_name="app.utils::greet",
        file_path="app/utils.py",
    )
    builder.add_edge("mod:a", "func:greet", EdgeType.CALLS, "main -> greet")
    doc = builder.build()
    graph_path = tmp_path / "graph.json"
    export_json(doc, graph_path)
    return graph_path


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------

class TestExitCodes:
    def test_scan_success_exits_zero(self):
        result = runner.invoke(app, ["scan", str(FIXTURE_PROJECT)])
        assert result.exit_code == 0

    def test_scan_nonexistent_path_exits_nonzero(self):
        result = runner.invoke(app, ["scan", "/nonexistent_path_xyz_99"])
        assert result.exit_code != 0

    def test_impact_success_exits_zero(self, tmp_path: Path):
        graph = _make_graph_file(tmp_path)
        result = runner.invoke(
            app, ["impact", "--node", "mod:a", "--graph", str(graph)]
        )
        assert result.exit_code == 0

    def test_impact_unknown_node_exits_one(self, tmp_path: Path):
        graph = _make_graph_file(tmp_path)
        result = runner.invoke(
            app,
            ["impact", "--node", "no_such_node_xyz", "--graph", str(graph)],
        )
        assert result.exit_code == 1

    def test_impact_bad_direction_exits_two(self, tmp_path: Path):
        graph = _make_graph_file(tmp_path)
        result = runner.invoke(
            app,
            ["impact", "--node", "mod:a", "--graph", str(graph),
             "--direction", "sideways"],
        )
        assert result.exit_code == 2

    def test_paths_success_exits_zero(self, tmp_path: Path):
        graph = _make_graph_file(tmp_path)
        result = runner.invoke(
            app,
            ["paths", "--from", "mod:a", "--to", "func:greet", "--graph", str(graph)],
        )
        assert result.exit_code == 0

    def test_paths_unknown_from_node_exits_one(self, tmp_path: Path):
        graph = _make_graph_file(tmp_path)
        result = runner.invoke(
            app,
            ["paths", "--from", "no_such_node_xyz", "--to", "func:greet",
             "--graph", str(graph)],
        )
        assert result.exit_code == 1

    def test_paths_unknown_to_node_exits_one(self, tmp_path: Path):
        graph = _make_graph_file(tmp_path)
        result = runner.invoke(
            app,
            ["paths", "--from", "mod:a", "--to", "no_such_node_xyz",
             "--graph", str(graph)],
        )
        assert result.exit_code == 1

    def test_audit_success_exits_zero(self, tmp_path: Path):
        graph = _make_graph_file(tmp_path)
        result = runner.invoke(app, ["audit", "--graph", str(graph)])
        assert result.exit_code == 0

    def test_summary_success_exits_zero(self, tmp_path: Path):
        graph = _make_graph_file(tmp_path)
        result = runner.invoke(app, ["summary", "--graph", str(graph)])
        assert result.exit_code == 0

    def test_version_flag_exits_zero(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0

    def test_agent_skill_exits_zero(self):
        result = runner.invoke(app, ["agent", "skill"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Missing / corrupt graph files
# ---------------------------------------------------------------------------

class TestMissingOrCorruptGraphFiles:
    def test_impact_missing_graph_exits_nonzero(self, tmp_path: Path):
        missing = tmp_path / "nonexistent_graph.json"
        result = runner.invoke(
            app, ["impact", "--node", "foo", "--graph", str(missing)]
        )
        assert result.exit_code != 0

    def test_audit_missing_graph_exits_nonzero(self, tmp_path: Path):
        missing = tmp_path / "nonexistent_graph.json"
        result = runner.invoke(app, ["audit", "--graph", str(missing)])
        assert result.exit_code != 0

    def test_summary_missing_graph_exits_nonzero(self, tmp_path: Path):
        missing = tmp_path / "nonexistent_graph.json"
        result = runner.invoke(app, ["summary", "--graph", str(missing)])
        assert result.exit_code != 0

    def test_paths_missing_graph_exits_nonzero(self, tmp_path: Path):
        missing = tmp_path / "nonexistent_graph.json"
        result = runner.invoke(
            app, ["paths", "--from", "a", "--to", "b", "--graph", str(missing)]
        )
        assert result.exit_code != 0

    def test_load_json_corrupt_file_raises(self, tmp_path: Path):
        corrupt = tmp_path / "corrupt.json"
        corrupt.write_text("{ this is not valid json }", encoding="utf-8")
        with pytest.raises(Exception):
            load_json(corrupt)

    def test_load_json_missing_file_raises(self, tmp_path: Path):
        missing = tmp_path / "missing.json"
        with pytest.raises(Exception):
            load_json(missing)


# ---------------------------------------------------------------------------
# --verbose flag output
# ---------------------------------------------------------------------------

class TestVerboseFlag:
    def test_verbose_scan_prints_scanning_header(self):
        result = runner.invoke(app, ["scan", str(FIXTURE_PROJECT), "--verbose"])
        assert result.exit_code == 0
        assert "Scanning" in result.output or "scanning" in result.output.lower()

    def test_verbose_scan_prints_ignore_patterns(self):
        result = runner.invoke(app, ["scan", str(FIXTURE_PROJECT), "--verbose"])
        assert result.exit_code == 0
        assert "ignore" in result.output.lower() or "pattern" in result.output.lower()

    def test_verbose_scan_prints_timings(self):
        result = runner.invoke(app, ["scan", str(FIXTURE_PROJECT), "--verbose"])
        assert result.exit_code == 0
        assert "Stage timings" in result.output or "timings" in result.output.lower()

    def test_verbose_scan_with_output_file(self, tmp_path: Path):
        out = tmp_path / "graph.json"
        result = runner.invoke(
            app, ["scan", str(FIXTURE_PROJECT), "-o", str(out), "--verbose"]
        )
        assert result.exit_code == 0
        assert out.exists()


# ---------------------------------------------------------------------------
# Export commands
# ---------------------------------------------------------------------------

class TestExportCommands:
    def test_export_json_creates_file(self, tmp_path: Path):
        out = tmp_path / "out.json"
        result = runner.invoke(
            app, ["export", "json", str(FIXTURE_PROJECT), "-o", str(out)]
        )
        assert result.exit_code == 0
        assert out.exists()
        data = json.loads(out.read_text())
        assert "nodes" in data and "edges" in data

    def test_export_neo4j_creates_csv_files(self, tmp_path: Path):
        out_dir = tmp_path / "neo4j"
        result = runner.invoke(
            app, ["export", "neo4j", str(FIXTURE_PROJECT), "-o", str(out_dir)]
        )
        assert result.exit_code == 0
        assert (out_dir / "nodes.csv").exists()
        assert (out_dir / "edges.csv").exists()

    def test_export_neo4j_csv_has_correct_headers(self, tmp_path: Path):
        out_dir = tmp_path / "neo4j"
        runner.invoke(
            app, ["export", "neo4j", str(FIXTURE_PROJECT), "-o", str(out_dir)]
        )
        nodes_csv = (out_dir / "nodes.csv").read_text(encoding="utf-8")
        assert ":ID" in nodes_csv
        assert ":LABEL" in nodes_csv

        edges_csv = (out_dir / "edges.csv").read_text(encoding="utf-8")
        assert ":START_ID" in edges_csv
        assert ":END_ID" in edges_csv


# ---------------------------------------------------------------------------
# Agent skill command
# ---------------------------------------------------------------------------

class TestAgentSkillCommand:
    def test_agent_skill_to_stdout(self):
        result = runner.invoke(app, ["agent", "skill"])
        assert result.exit_code == 0
        assert "constrictor" in result.output.lower()

    def test_agent_skill_to_file(self, tmp_path: Path):
        out = tmp_path / "SKILL.md"
        result = runner.invoke(app, ["agent", "skill", "-o", str(out)])
        assert result.exit_code == 0
        assert out.exists()
        content = out.read_text()
        assert len(content) > 100

    def test_agent_skill_contains_required_sections(self, tmp_path: Path):
        out = tmp_path / "SKILL.md"
        runner.invoke(app, ["agent", "skill", "-o", str(out)])
        content = out.read_text()
        for section in ("Quick Start", "Workflow", "constrictor scan"):
            assert section in content, f"Missing section: {section}"


# ---------------------------------------------------------------------------
# export_json file I/O
# ---------------------------------------------------------------------------

class TestExportJsonIO:
    def test_export_json_creates_parent_dirs(self, tmp_path: Path):
        nested = tmp_path / "a" / "b" / "graph.json"
        builder = GraphBuilder()
        builder.add_node(
            "mod:x", NodeType.MODULE, "x", qualified_name="x", display_name="x"
        )
        doc = builder.build()
        export_json(doc, nested)
        assert nested.exists()

    def test_export_json_returns_string_without_path(self):
        builder = GraphBuilder()
        doc = builder.build()
        result = export_json(doc)
        assert isinstance(result, str)
        data = json.loads(result)
        assert "nodes" in data
