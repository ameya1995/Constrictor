"""Tests for the SKILL.md generator (Phase 8)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from constrictor import __version__
from constrictor.agent.skill import generate_skill_md


# ── Helpers ───────────────────────────────────────────────────────────────

def _render() -> str:
    """Return a freshly rendered SKILL.md string."""
    return generate_skill_md()


# ── Rendering ─────────────────────────────────────────────────────────────

class TestRenderWithoutErrors:
    def test_returns_string(self) -> None:
        result = _render()
        assert isinstance(result, str)

    def test_non_empty(self) -> None:
        result = _render()
        assert len(result) > 500, "Expected substantial content in SKILL.md"

    def test_version_injected(self) -> None:
        result = _render()
        assert __version__ in result, f"Expected version {__version__!r} in output"

    def test_no_jinja_delimiters_remain(self) -> None:
        result = _render()
        assert "{{" not in result, "Unrendered Jinja2 block '{{' found in output"
        assert "{%" not in result, "Unrendered Jinja2 block '{%' found in output"


# ── Required sections ─────────────────────────────────────────────────────

REQUIRED_SECTIONS = [
    "Quick Start",
    "Commands",
    "Workflow",
    "Reading the Output",
    "Prompt Templates",
    "Operational Notes",
    "Cross-Agent Install Shape",
]


@pytest.mark.parametrize("section", REQUIRED_SECTIONS)
def test_required_section_present(section: str) -> None:
    result = _render()
    assert section in result, f"Required section {section!r} not found in SKILL.md"


# ── Frontmatter ───────────────────────────────────────────────────────────

class TestFrontmatter:
    def test_starts_with_yaml_frontmatter(self) -> None:
        result = _render()
        assert result.startswith("---"), "SKILL.md must start with YAML frontmatter '---'"

    def test_frontmatter_contains_name(self) -> None:
        result = _render()
        assert "name: constrictor" in result

    def test_frontmatter_contains_description(self) -> None:
        result = _render()
        assert "description:" in result


# ── CLI commands ──────────────────────────────────────────────────────────

REQUIRED_COMMANDS = [
    "constrictor scan",
    "constrictor impact",
    "constrictor paths",
    "constrictor audit",
    "constrictor summary",
    "constrictor watch",
    "constrictor export",
    "constrictor serve",
    "constrictor agent skill",
]


@pytest.mark.parametrize("command", REQUIRED_COMMANDS)
def test_command_referenced(command: str) -> None:
    result = _render()
    assert command in result, f"Expected command {command!r} to appear in SKILL.md"


# ── Certainty levels ──────────────────────────────────────────────────────

class TestCertaintyDocs:
    def test_all_certainty_levels_documented(self) -> None:
        result = _render()
        for level in ("UNRESOLVED", "AMBIGUOUS", "INFERRED", "EXACT"):
            assert level in result, f"Certainty level {level!r} not documented"


# ── Prompt templates ──────────────────────────────────────────────────────

class TestPromptTemplates:
    def test_pre_refactor_template(self) -> None:
        result = _render()
        assert "Pre-refactor" in result or "pre-refactor" in result.lower()

    def test_dependency_audit_template(self) -> None:
        result = _render()
        assert "Dependency audit" in result or "dependency audit" in result.lower()

    def test_cross_service_template(self) -> None:
        result = _render()
        assert "Cross-service" in result or "cross-service" in result.lower()


# ── File output ───────────────────────────────────────────────────────────

class TestFileOutput:
    def test_writes_to_file(self, tmp_path: Path) -> None:
        dest = tmp_path / "SKILL.md"
        result = generate_skill_md(output_path=dest)
        assert dest.exists(), "Output file was not created"
        content = dest.read_text(encoding="utf-8")
        assert content == result

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        dest = tmp_path / "nested" / "dir" / "SKILL.md"
        generate_skill_md(output_path=dest)
        assert dest.exists()

    def test_file_and_return_value_match(self, tmp_path: Path) -> None:
        dest = tmp_path / "SKILL.md"
        returned = generate_skill_md(output_path=dest)
        written = dest.read_text(encoding="utf-8")
        assert returned == written


# ── CLI integration ───────────────────────────────────────────────────────

class TestCLI:
    def test_agent_skill_stdout(self) -> None:
        from typer.testing import CliRunner
        from constrictor.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["agent", "skill"])
        assert result.exit_code == 0, result.output
        assert "Quick Start" in result.output

    def test_agent_skill_to_file(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner
        from constrictor.cli.main import app

        dest = tmp_path / "SKILL.md"
        runner = CliRunner()
        result = runner.invoke(app, ["agent", "skill", "-o", str(dest)])
        assert result.exit_code == 0, result.output
        assert dest.exists()
        content = dest.read_text(encoding="utf-8")
        assert "Quick Start" in content
        assert __version__ in content
