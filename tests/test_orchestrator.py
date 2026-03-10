"""End-to-end tests for the scan orchestrator using the simple_project fixture."""
from __future__ import annotations

from pathlib import Path

import pytest

from constrictor.core.models import ScanOptions
from constrictor.core.orchestrator import run_scan
from constrictor.graph.models import EdgeType, NodeType

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "simple_project"


@pytest.fixture(scope="module")
def simple_doc():
    options = ScanOptions(root_path=FIXTURE_ROOT)
    return run_scan(options)


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------

def test_returns_graph_document(simple_doc):
    from constrictor.graph.models import GraphDocument
    assert isinstance(simple_doc, GraphDocument)


def test_has_nodes(simple_doc):
    assert simple_doc.statistics.total_nodes > 0


def test_has_edges(simple_doc):
    assert simple_doc.statistics.total_edges > 0


def test_has_scan_metadata(simple_doc):
    assert simple_doc.scan_metadata is not None
    assert simple_doc.scan_metadata.root_path == str(FIXTURE_ROOT)
    assert simple_doc.scan_metadata.constrictor_version


def test_file_counts(simple_doc):
    stats = simple_doc.statistics
    # simple_project has: app/__init__.py, app/main.py, app/utils.py, app/models.py,
    # tests/test_main.py = 5 .py files; setup.py is a config file
    assert stats.total_files >= 4
    assert stats.parsed_files == stats.total_files
    assert stats.failed_files == 0


# ---------------------------------------------------------------------------
# Node types present
# ---------------------------------------------------------------------------

def test_module_nodes_present(simple_doc):
    module_nodes = [n for n in simple_doc.nodes if n.type == NodeType.MODULE]
    assert module_nodes, "Expected MODULE nodes"


def test_function_nodes_present(simple_doc):
    func_nodes = [n for n in simple_doc.nodes if n.type == NodeType.FUNCTION]
    func_names = {n.name for n in func_nodes}
    # app/utils.py defines greet and helper
    assert "greet" in func_names
    assert "helper" in func_names


def test_class_nodes_present(simple_doc):
    class_nodes = [n for n in simple_doc.nodes if n.type == NodeType.CLASS]
    class_names = {n.name for n in class_nodes}
    # app/models.py defines User
    assert "User" in class_names


def test_method_nodes_present(simple_doc):
    method_nodes = [n for n in simple_doc.nodes if n.type == NodeType.METHOD]
    method_names = {n.name for n in method_nodes}
    # User.__init__ and User.__repr__ are defined
    assert "__init__" in method_names


# ---------------------------------------------------------------------------
# Edge types present
# ---------------------------------------------------------------------------

def test_imports_edges_present(simple_doc):
    import_edges = [
        e for e in simple_doc.edges
        if e.type in (EdgeType.IMPORTS, EdgeType.IMPORTS_FROM)
    ]
    assert import_edges, "Expected import edges"


def test_contains_edges_present(simple_doc):
    contains_edges = [e for e in simple_doc.edges if e.type == EdgeType.CONTAINS]
    assert contains_edges, "Expected CONTAINS edges"


def test_calls_edges_present(simple_doc):
    call_edges = [e for e in simple_doc.edges if e.type == EdgeType.CALLS]
    assert call_edges, "Expected CALLS edges"


# ---------------------------------------------------------------------------
# Specific graph relationships
# ---------------------------------------------------------------------------

def test_app_main_imports_utils(simple_doc):
    """app.main should have an import edge to app.utils."""
    import_edges = [
        e for e in simple_doc.edges
        if e.type in (EdgeType.IMPORTS, EdgeType.IMPORTS_FROM)
    ]
    relevant = [
        e for e in import_edges
        if "utils" in e.display_name.lower() or "utils" in (e.metadata.get("names", ""))
    ]
    assert relevant, "Expected app.main to import from app.utils"


def test_run_app_function_exists(simple_doc):
    """app.main defines run_app()."""
    func_nodes = [n for n in simple_doc.nodes if n.type == NodeType.FUNCTION]
    assert any("run_app" in n.name for n in func_nodes)


# ---------------------------------------------------------------------------
# Statistics sanity
# ---------------------------------------------------------------------------

def test_node_type_counts_populated(simple_doc):
    counts = simple_doc.statistics.node_type_counts
    assert counts
    assert "MODULE" in counts or "FUNCTION" in counts


def test_edge_type_counts_populated(simple_doc):
    counts = simple_doc.statistics.edge_type_counts
    assert counts


def test_stage_timings_recorded(simple_doc):
    meta = simple_doc.scan_metadata
    assert meta is not None
    assert len(meta.timings) >= 3  # scan, parse, at least one extractor


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_scan_is_deterministic():
    """Running the scan twice should produce identical node/edge counts."""
    options = ScanOptions(root_path=FIXTURE_ROOT)
    doc1 = run_scan(options)
    doc2 = run_scan(options)

    assert doc1.statistics.total_nodes == doc2.statistics.total_nodes
    assert doc1.statistics.total_edges == doc2.statistics.total_edges

    ids1 = {n.id for n in doc1.nodes}
    ids2 = {n.id for n in doc2.nodes}
    assert ids1 == ids2
