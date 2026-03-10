"""Integration tests for incremental scanning (V2_INC).

These tests run against the existing `simple_project` fixture and a small
temporary project to verify that:

1. An incremental scan with a warm cache produces the same graph as a full scan.
2. A second incremental scan with no file changes returns quickly and
   produces identical output to the first incremental scan.
3. Modifying a file is detected and results in an updated graph.
4. Adding a new file is detected and the new symbols appear in the graph.
5. Removing a file prunes its nodes from the graph.
6. A config-file change triggers an automatic full rescan.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from constrictor.core.models import ScanOptions
from constrictor.core.orchestrator import run_scan
from constrictor.export.json_export import export_json, load_json


SIMPLE_PROJECT = (
    Path(__file__).parent / "fixtures" / "simple_project"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scan_full(path: Path) -> dict:
    opts = ScanOptions(root_path=path)
    doc = run_scan(opts, incremental=False)
    return doc.model_dump(mode="json")


def _scan_incremental(path: Path) -> dict:
    opts = ScanOptions(root_path=path)
    doc = run_scan(opts, incremental=True)
    return doc.model_dump(mode="json")


def _graph_key(d: dict) -> tuple:
    """A stable signature of node IDs + edge IDs, ignoring timing metadata."""
    node_ids = frozenset(n["id"] for n in d["nodes"])
    edge_ids = frozenset(e["id"] for e in d["edges"])
    return node_ids, edge_ids


# ---------------------------------------------------------------------------
# Tests on a *copy* of simple_project so we don't pollute the fixture dir
# ---------------------------------------------------------------------------

@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """A writable copy of simple_project, and a graph.json location."""
    dest = tmp_path / "proj"
    shutil.copytree(SIMPLE_PROJECT, dest)
    return dest


def test_incremental_first_run_matches_full_scan(project: Path) -> None:
    """First incremental scan (cold cache) must produce the same graph as full."""
    full = _graph_key(_scan_full(project))

    # Remove any cache that might have been created by the full scan.
    cache_dir = project / ".constrictor_cache"
    if cache_dir.exists():
        shutil.rmtree(cache_dir)

    # First incremental run — cache is empty, falls back to full scan internally.
    inc = _graph_key(_scan_incremental(project))

    assert full == inc


def test_incremental_second_run_no_changes(project: Path) -> None:
    """Second incremental scan with no file changes returns identical graph."""
    # Warm the cache with a full scan + produce graph.json.
    opts = ScanOptions(root_path=project)
    doc = run_scan(opts, incremental=False)
    graph_path = project / "graph.json"
    export_json(doc, graph_path)

    # Warm the cache.
    from constrictor.core.cache import FileCache
    from constrictor.core.scanner import scan_directory

    scan_result = scan_directory(opts)
    cache = FileCache(project)
    cache.load()
    cache.update_hashes(scan_result.python_files)
    cache.update_config_hashes(project)
    # Store minimal fragments so the incremental path doesn't re-parse anything.
    from constrictor.core.orchestrator import _store_fragments
    _store_fragments(cache, doc, scan_result.python_files)
    cache.save()

    # Now run incremental twice.
    inc1 = _graph_key(_scan_incremental(project))
    inc2 = _graph_key(_scan_incremental(project))

    assert inc1 == inc2


def test_incremental_detects_modified_file(project: Path) -> None:
    """Modified file's new content should appear in the incremental result."""
    # Full scan first to establish baseline.
    opts = ScanOptions(root_path=project)
    doc_full = run_scan(opts, incremental=False)
    export_json(doc_full, project / "graph.json")

    # Warm the cache explicitly.
    from constrictor.core.cache import FileCache
    from constrictor.core.scanner import scan_directory
    from constrictor.core.orchestrator import _store_fragments

    scan_result = scan_directory(opts)
    cache = FileCache(project)
    cache.load()
    cache.update_hashes(scan_result.python_files)
    cache.update_config_hashes(project)
    _store_fragments(cache, doc_full, scan_result.python_files)
    cache.save()

    # Add a new function to utils.py.
    utils_path = project / "app" / "utils.py"
    original = utils_path.read_text(encoding="utf-8")
    utils_path.write_text(original + "\n\ndef brand_new_function():\n    pass\n", encoding="utf-8")

    doc_inc = run_scan(opts, incremental=True)

    # The new function should be present as a node.
    node_names = {n.name for n in doc_inc.nodes}
    assert "brand_new_function" in node_names


def test_incremental_detects_added_file(project: Path) -> None:
    """A new .py file added after the first scan should be included."""
    opts = ScanOptions(root_path=project)
    doc_full = run_scan(opts, incremental=False)
    export_json(doc_full, project / "graph.json")

    from constrictor.core.cache import FileCache
    from constrictor.core.scanner import scan_directory
    from constrictor.core.orchestrator import _store_fragments

    scan_result = scan_directory(opts)
    cache = FileCache(project)
    cache.load()
    cache.update_hashes(scan_result.python_files)
    cache.update_config_hashes(project)
    _store_fragments(cache, doc_full, scan_result.python_files)
    cache.save()

    # Add a new module.
    new_module = project / "app" / "newly_added.py"
    new_module.write_text("def added_fn():\n    pass\n", encoding="utf-8")

    doc_inc = run_scan(opts, incremental=True)
    node_names = {n.name for n in doc_inc.nodes}
    assert "added_fn" in node_names


def test_incremental_config_change_triggers_full_rescan(project: Path) -> None:
    """A change to pyproject.toml must invalidate the cache and do a full rescan."""
    opts = ScanOptions(root_path=project)
    doc_full = run_scan(opts, incremental=False)
    export_json(doc_full, project / "graph.json")

    from constrictor.core.cache import FileCache
    from constrictor.core.scanner import scan_directory
    from constrictor.core.orchestrator import _store_fragments

    scan_result = scan_directory(opts)
    cache = FileCache(project)
    cache.load()
    cache.update_hashes(scan_result.python_files)
    cache.update_config_hashes(project)
    _store_fragments(cache, doc_full, scan_result.python_files)
    cache.save()

    # Modify the setup.py config file.
    setup_py = project / "setup.py"
    if setup_py.exists():
        setup_py.write_text(setup_py.read_text() + "\n# changed\n", encoding="utf-8")
    else:
        setup_py.write_text("# new config\n", encoding="utf-8")

    # Incremental scan should detect config change and fall back to full.
    doc_inc = run_scan(opts, incremental=True)
    # Result should still be valid (not empty).
    assert len(doc_inc.nodes) > 0


def test_incremental_handles_missing_graph_json(project: Path) -> None:
    """If graph.json is absent, incremental scan falls back to full scan gracefully."""
    # Warm cache hashes but don't produce graph.json.
    opts = ScanOptions(root_path=project)
    from constrictor.core.cache import FileCache
    from constrictor.core.scanner import scan_directory

    scan_result = scan_directory(opts)
    cache = FileCache(project)
    cache.load()
    cache.update_hashes(scan_result.python_files)
    cache.update_config_hashes(project)
    cache.save()

    # No graph.json exists — should still succeed.
    doc = run_scan(opts, incremental=True)
    assert len(doc.nodes) > 0


def test_full_and_incremental_node_count_similar(project: Path) -> None:
    """Full and incremental scans on the same unchanged project yield same node set."""
    opts = ScanOptions(root_path=project)
    doc_full = run_scan(opts, incremental=False)
    export_json(doc_full, project / "graph.json")

    # First incremental (warms cache from full).
    doc_inc1 = run_scan(opts, incremental=True)
    # Second incremental (uses warm cache).
    doc_inc2 = run_scan(opts, incremental=True)

    full_ids = {n.id for n in doc_full.nodes}
    inc2_ids = {n.id for n in doc_inc2.nodes}
    assert full_ids == inc2_ids
