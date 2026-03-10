from __future__ import annotations

from pathlib import Path

import pytest

from constrictor.core.ignore import load_ignore_patterns, should_exclude


def test_hardcoded_defaults_always_present(tmp_path: Path) -> None:
    patterns = load_ignore_patterns(tmp_path)
    assert "__pycache__" in patterns
    assert ".git" in patterns
    assert ".venv" in patterns
    assert "venv" in patterns
    assert "node_modules" in patterns
    assert "dist" in patterns
    assert "build" in patterns


def test_reads_constrictor_ignore_from_root(tmp_path: Path) -> None:
    ignore_file = tmp_path / ".constrictor_ignore"
    ignore_file.write_text("my_custom_dir\n# a comment\n\nanother_pattern\n")

    patterns = load_ignore_patterns(tmp_path)
    assert "my_custom_dir" in patterns
    assert "another_pattern" in patterns
    # Comments and blank lines should not be included
    assert "# a comment" not in patterns
    assert "" not in patterns


def test_comment_lines_ignored(tmp_path: Path) -> None:
    ignore_file = tmp_path / ".constrictor_ignore"
    ignore_file.write_text("# this is a comment\n  # indented comment\nreal_pattern\n")

    patterns = load_ignore_patterns(tmp_path)
    assert "# this is a comment" not in patterns
    assert "  # indented comment" not in patterns
    assert "real_pattern" in patterns


def test_blank_lines_ignored(tmp_path: Path) -> None:
    ignore_file = tmp_path / ".constrictor_ignore"
    ignore_file.write_text("\n\nvalid_pattern\n\n")

    patterns = load_ignore_patterns(tmp_path)
    assert "" not in patterns
    assert "valid_pattern" in patterns


def test_extra_patterns_merged(tmp_path: Path) -> None:
    patterns = load_ignore_patterns(tmp_path, extra_patterns=["custom_dir", "*.log"])
    assert "custom_dir" in patterns
    assert "*.log" in patterns


def test_extra_exclude_file_merged(tmp_path: Path) -> None:
    extra_file = tmp_path / "extra_ignore.txt"
    extra_file.write_text("extra_pattern\nanother_extra\n")

    patterns = load_ignore_patterns(tmp_path, extra_exclude_files=[extra_file])
    assert "extra_pattern" in patterns
    assert "another_extra" in patterns


def test_missing_constrictor_ignore_is_ok(tmp_path: Path) -> None:
    # No .constrictor_ignore file -- should not raise
    patterns = load_ignore_patterns(tmp_path)
    assert len(patterns) > 0  # defaults still present


def test_should_exclude_by_exact_name(tmp_path: Path) -> None:
    patterns = ["__pycache__", ".git"]
    assert should_exclude(tmp_path / "__pycache__", patterns)
    assert should_exclude(tmp_path / ".git", patterns)
    assert not should_exclude(tmp_path / "mymodule.py", patterns)


def test_should_exclude_glob_pattern(tmp_path: Path) -> None:
    patterns = ["*.egg-info", "*.pyc"]
    assert should_exclude(tmp_path / "mypackage.egg-info", patterns)
    assert should_exclude(tmp_path / "module.pyc", patterns)
    assert not should_exclude(tmp_path / "module.py", patterns)


def test_should_not_exclude_unmatched(tmp_path: Path) -> None:
    patterns = ["__pycache__"]
    assert not should_exclude(tmp_path / "src", patterns)
    assert not should_exclude(tmp_path / "main.py", patterns)


def test_glob_pattern_dist(tmp_path: Path) -> None:
    patterns = load_ignore_patterns(tmp_path)
    assert should_exclude(tmp_path / "dist", patterns)
    assert should_exclude(tmp_path / "build", patterns)
