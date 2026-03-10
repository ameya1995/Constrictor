"""Tests for Neo4j CSV export."""
from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from constrictor.core.models import Certainty
from constrictor.export.neo4j_export import (
    _EDGES_HEADERS,
    _NODES_HEADERS,
    export_neo4j,
    export_neo4j_strings,
    _node_type_to_label,
)
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.models import EdgeType, NodeType


# ─── Helpers ──────────────────────────────────────────────────────────────


def _build_simple_doc():
    builder = GraphBuilder()
    builder.add_node(
        "mod:aaa",
        NodeType.MODULE,
        "app.main",
        qualified_name="app.main",
        display_name="app.main",
        file_path="app/main.py",
    )
    builder.add_node(
        "func:bbb",
        NodeType.FUNCTION,
        "greet",
        qualified_name="app.utils.greet",
        display_name="greet",
        file_path="app/utils.py",
    )
    builder.add_edge(
        "mod:aaa",
        "func:bbb",
        EdgeType.CALLS,
        display_name="main -> greet",
        certainty=Certainty.EXACT,
    )
    return builder.build(scan_metadata=None, warnings=[])


# ─── _node_type_to_label ──────────────────────────────────────────────────


def test_label_module():
    assert _node_type_to_label("MODULE") == "Module"


def test_label_external_module():
    # Underscores stripped, then title-cased
    assert _node_type_to_label("EXTERNAL_MODULE") == "Externalmodule"


def test_label_function():
    assert _node_type_to_label("FUNCTION") == "Function"


# ─── CSV header correctness ───────────────────────────────────────────────


def test_nodes_csv_headers():
    doc = _build_simple_doc()
    nodes_str, _ = export_neo4j_strings(doc)
    reader = csv.reader(io.StringIO(nodes_str))
    header = next(reader)
    assert header == _NODES_HEADERS


def test_edges_csv_headers():
    doc = _build_simple_doc()
    _, edges_str = export_neo4j_strings(doc)
    reader = csv.reader(io.StringIO(edges_str))
    header = next(reader)
    assert header == _EDGES_HEADERS


# ─── CSV content correctness ──────────────────────────────────────────────


def test_nodes_csv_row_count():
    doc = _build_simple_doc()
    nodes_str, _ = export_neo4j_strings(doc)
    rows = list(csv.reader(io.StringIO(nodes_str)))
    # header + 2 nodes
    assert len(rows) == 3


def test_edges_csv_row_count():
    doc = _build_simple_doc()
    _, edges_str = export_neo4j_strings(doc)
    rows = list(csv.reader(io.StringIO(edges_str)))
    # header + 1 edge
    assert len(rows) == 2


def test_nodes_csv_ids_match():
    doc = _build_simple_doc()
    nodes_str, _ = export_neo4j_strings(doc)
    rows = list(csv.DictReader(io.StringIO(nodes_str)))
    ids = {r[":ID"] for r in rows}
    assert "mod:aaa" in ids
    assert "func:bbb" in ids


def test_nodes_csv_type_column():
    doc = _build_simple_doc()
    nodes_str, _ = export_neo4j_strings(doc)
    rows = list(csv.DictReader(io.StringIO(nodes_str)))
    types = {r["type:string"] for r in rows}
    assert "MODULE" in types
    assert "FUNCTION" in types


def test_edges_csv_start_end_ids():
    doc = _build_simple_doc()
    _, edges_str = export_neo4j_strings(doc)
    rows = list(csv.DictReader(io.StringIO(edges_str)))
    assert len(rows) == 1
    assert rows[0][":START_ID"] == "mod:aaa"
    assert rows[0][":END_ID"] == "func:bbb"
    assert rows[0][":TYPE"] == "CALLS"


def test_edges_csv_certainty_column():
    doc = _build_simple_doc()
    _, edges_str = export_neo4j_strings(doc)
    rows = list(csv.DictReader(io.StringIO(edges_str)))
    assert rows[0]["certainty:string"] == "EXACT"


def test_nodes_csv_label_column():
    doc = _build_simple_doc()
    nodes_str, _ = export_neo4j_strings(doc)
    rows = list(csv.DictReader(io.StringIO(nodes_str)))
    mod_row = next(r for r in rows if r[":ID"] == "mod:aaa")
    assert mod_row[":LABEL"] == "Module"


# ─── File export ──────────────────────────────────────────────────────────


def test_export_neo4j_writes_files(tmp_path: Path):
    doc = _build_simple_doc()
    export_neo4j(doc, tmp_path)
    assert (tmp_path / "nodes.csv").exists()
    assert (tmp_path / "edges.csv").exists()


def test_export_neo4j_creates_output_dir(tmp_path: Path):
    doc = _build_simple_doc()
    out_dir = tmp_path / "nested" / "output"
    export_neo4j(doc, out_dir)
    assert (out_dir / "nodes.csv").exists()


def test_export_neo4j_file_content(tmp_path: Path):
    doc = _build_simple_doc()
    export_neo4j(doc, tmp_path)
    rows = list(csv.DictReader((tmp_path / "nodes.csv").open()))
    ids = {r[":ID"] for r in rows}
    assert "mod:aaa" in ids
    assert "func:bbb" in ids


# ─── Empty document ───────────────────────────────────────────────────────


def test_empty_document():
    builder = GraphBuilder()
    doc = builder.build(scan_metadata=None, warnings=[])
    nodes_str, edges_str = export_neo4j_strings(doc)

    node_rows = list(csv.reader(io.StringIO(nodes_str)))
    edge_rows = list(csv.reader(io.StringIO(edges_str)))

    assert node_rows == [_NODES_HEADERS]
    assert edge_rows == [_EDGES_HEADERS]
