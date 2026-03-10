"""Tests for src/constrictor/core/cache.py"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from constrictor.core.cache import (
    DiffResult,
    FileCache,
    FileFragment,
    hash_file,
)
from constrictor.core.models import Certainty
from constrictor.graph.models import GraphEdge, GraphNode, NodeType, EdgeType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """A minimal project directory with two Python files."""
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def cache(tmp_project: Path) -> FileCache:
    return FileCache(tmp_project)


# ---------------------------------------------------------------------------
# hash_file
# ---------------------------------------------------------------------------

def test_hash_file_returns_hex_string(tmp_path: Path) -> None:
    p = tmp_path / "f.py"
    p.write_text("hello\n", encoding="utf-8")
    h = hash_file(p)
    assert isinstance(h, str)
    assert len(h) == 64


def test_hash_file_deterministic(tmp_path: Path) -> None:
    p = tmp_path / "f.py"
    p.write_text("hello\n", encoding="utf-8")
    assert hash_file(p) == hash_file(p)


def test_hash_file_changes_on_content_change(tmp_path: Path) -> None:
    p = tmp_path / "f.py"
    p.write_text("hello\n", encoding="utf-8")
    h1 = hash_file(p)
    p.write_text("world\n", encoding="utf-8")
    h2 = hash_file(p)
    assert h1 != h2


def test_hash_file_missing_returns_empty(tmp_path: Path) -> None:
    h = hash_file(tmp_path / "nonexistent.py")
    assert h == ""


# ---------------------------------------------------------------------------
# FileCache load / save
# ---------------------------------------------------------------------------

def test_load_when_no_cache_gives_empty(cache: FileCache) -> None:
    cache.load()
    assert cache.is_empty


def test_save_and_reload(cache: FileCache, tmp_project: Path) -> None:
    files = list(tmp_project.glob("*.py"))
    cache.load()
    cache.update_hashes(files)
    cache.save()

    cache2 = FileCache(tmp_project)
    cache2.load()
    assert not cache2.is_empty


def test_save_creates_cache_dir(cache: FileCache, tmp_project: Path) -> None:
    cache.load()
    cache.update_hashes([tmp_project / "a.py"])
    cache.save()
    assert (tmp_project / ".constrictor_cache" / "hashes.json").exists()


# ---------------------------------------------------------------------------
# DiffResult
# ---------------------------------------------------------------------------

def test_diff_all_added_when_cache_empty(cache: FileCache, tmp_project: Path) -> None:
    cache.load()
    files = list(tmp_project.glob("*.py"))
    diff = cache.diff(files)
    assert set(diff.added) == {p.resolve() for p in files}
    assert diff.unchanged == []
    assert diff.changed == []
    assert diff.removed == []


def test_diff_all_unchanged_after_warm(cache: FileCache, tmp_project: Path) -> None:
    files = list(tmp_project.glob("*.py"))
    cache.load()
    cache.update_hashes(files)
    cache.save()

    cache2 = FileCache(tmp_project)
    cache2.load()
    diff = cache2.diff(files)
    assert len(diff.unchanged) == 2
    assert diff.added == []
    assert diff.changed == []
    assert diff.removed == []


def test_diff_detects_changed_file(cache: FileCache, tmp_project: Path) -> None:
    files = list(tmp_project.glob("*.py"))
    cache.load()
    cache.update_hashes(files)
    cache.save()

    # Modify one file.
    (tmp_project / "a.py").write_text("x = 99\n", encoding="utf-8")

    cache2 = FileCache(tmp_project)
    cache2.load()
    diff = cache2.diff(files)
    assert len(diff.changed) == 1
    assert diff.changed[0].name == "a.py"
    assert len(diff.unchanged) == 1


def test_diff_detects_removed_file(cache: FileCache, tmp_project: Path) -> None:
    files = list(tmp_project.glob("*.py"))
    cache.load()
    cache.update_hashes(files)
    cache.save()

    # Remove one file from the list (simulate deletion).
    remaining = [f for f in files if f.name != "b.py"]

    cache2 = FileCache(tmp_project)
    cache2.load()
    diff = cache2.diff(remaining)
    assert len(diff.removed) == 1
    assert diff.removed[0].name == "b.py"


def test_diff_needs_reanalysis_combines_changed_and_added(
    cache: FileCache, tmp_project: Path
) -> None:
    files = [tmp_project / "a.py"]
    cache.load()
    cache.update_hashes(files)
    cache.save()

    all_files = list(tmp_project.glob("*.py"))
    cache2 = FileCache(tmp_project)
    cache2.load()
    diff = cache2.diff(all_files)
    reanalysis = diff.needs_reanalysis
    names = {p.name for p in reanalysis}
    assert "b.py" in names  # added


# ---------------------------------------------------------------------------
# Fragment store / load
# ---------------------------------------------------------------------------

def _make_node(id: str, name: str, file_path: str) -> GraphNode:
    return GraphNode(
        id=id,
        type=NodeType.FUNCTION,
        name=name,
        qualified_name=name,
        display_name=name,
        file_path=file_path,
        certainty=Certainty.EXACT,
    )


def _make_edge(src: str, tgt: str, file_path: str) -> GraphEdge:
    return GraphEdge(
        id=f"edge:{src}_{tgt}",
        source_id=src,
        target_id=tgt,
        type=EdgeType.CALLS,
        display_name=f"{src} -> {tgt}",
        file_path=file_path,
        certainty=Certainty.EXACT,
    )


def test_store_and_load_fragment(cache: FileCache, tmp_project: Path) -> None:
    cache.load()
    fp = str(tmp_project / "a.py")
    node = _make_node("func:aaa", "foo", fp)
    edge = _make_edge("func:aaa", "func:bbb", fp)
    fragment = FileFragment(file_path=fp, nodes=[node], edges=[edge])

    cache.store_fragment(fragment)

    loaded = cache.load_fragment(tmp_project / "a.py")
    assert loaded is not None
    assert len(loaded.nodes) == 1
    assert loaded.nodes[0].id == "func:aaa"
    assert len(loaded.edges) == 1


def test_load_fragment_returns_none_for_unknown_file(
    cache: FileCache, tmp_project: Path
) -> None:
    cache.load()
    assert cache.load_fragment(tmp_project / "nonexistent.py") is None


def test_delete_fragment(cache: FileCache, tmp_project: Path) -> None:
    cache.load()
    fp = str(tmp_project / "a.py")
    fragment = FileFragment(file_path=fp, nodes=[], edges=[])
    cache.store_fragment(fragment)
    assert cache.load_fragment(tmp_project / "a.py") is not None

    cache.delete_fragment(tmp_project / "a.py")
    assert cache.load_fragment(tmp_project / "a.py") is None


def test_delete_fragment_noop_if_not_present(
    cache: FileCache, tmp_project: Path
) -> None:
    cache.load()
    # Should not raise.
    cache.delete_fragment(tmp_project / "nonexistent.py")


def test_store_fragments_batch(cache: FileCache, tmp_project: Path) -> None:
    cache.load()
    frags = [
        FileFragment(file_path=str(tmp_project / "a.py"), nodes=[], edges=[]),
        FileFragment(file_path=str(tmp_project / "b.py"), nodes=[], edges=[]),
    ]
    cache.store_fragments(frags)
    assert cache.load_fragment(tmp_project / "a.py") is not None
    assert cache.load_fragment(tmp_project / "b.py") is not None


# ---------------------------------------------------------------------------
# Config files changed
# ---------------------------------------------------------------------------

def test_config_files_changed_false_when_cache_fresh(
    cache: FileCache, tmp_project: Path
) -> None:
    (tmp_project / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    cache.load()
    cache.update_config_hashes(tmp_project)
    cache.save()

    cache2 = FileCache(tmp_project)
    cache2.load()
    assert not cache2.config_files_changed(tmp_project)


def test_config_files_changed_true_after_modification(
    cache: FileCache, tmp_project: Path
) -> None:
    cfg = tmp_project / "pyproject.toml"
    cfg.write_text("[project]\nname='x'\n", encoding="utf-8")
    cache.load()
    cache.update_config_hashes(tmp_project)
    cache.save()

    cfg.write_text("[project]\nname='changed'\n", encoding="utf-8")

    cache2 = FileCache(tmp_project)
    cache2.load()
    assert cache2.config_files_changed(tmp_project)


def test_config_files_changed_true_when_cache_empty(
    cache: FileCache, tmp_project: Path
) -> None:
    (tmp_project / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    cache.load()
    assert cache.config_files_changed(tmp_project)


def test_config_files_changed_false_when_no_config_files(
    cache: FileCache, tmp_project: Path
) -> None:
    cache.load()
    cache.update_config_hashes(tmp_project)
    # No config files exist in tmp_project -> should return False.
    assert not cache.config_files_changed(tmp_project)


# ---------------------------------------------------------------------------
# remove_hashes
# ---------------------------------------------------------------------------

def test_remove_hashes(cache: FileCache, tmp_project: Path) -> None:
    files = list(tmp_project.glob("*.py"))
    cache.load()
    cache.update_hashes(files)

    cache.remove_hashes([tmp_project / "a.py"])

    diff = cache.diff([tmp_project / "b.py"])
    # b.py still present and unchanged; a.py entry gone so if we diff with all
    # files it appears as "added"
    diff_all = cache.diff(list(tmp_project.glob("*.py")))
    names_added = {p.name for p in diff_all.added}
    assert "a.py" in names_added
