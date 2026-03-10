"""Tests for the import extractor."""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from constrictor.analysis.imports import ImportExtractor, _resolve_relative_import
from constrictor.core.models import Certainty, ScanWarning
from constrictor.core.parser import ParsedModule
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.models import EdgeType, NodeType


def _make_module(module_name: str, source: str, file_path: str = "") -> ParsedModule:
    tree = ast.parse(textwrap.dedent(source))
    return ParsedModule(
        file_path=Path(file_path or f"/fake/{module_name.replace('.', '/')}.py"),
        module_name=module_name,
        ast_tree=tree,
    )


def _run_extractor(*modules: ParsedModule) -> tuple[GraphBuilder, list[ScanWarning]]:
    builder = GraphBuilder()
    warnings: list[ScanWarning] = []
    extractor = ImportExtractor()
    extractor.contribute(list(modules), builder, warnings)
    return builder, warnings


# ---------------------------------------------------------------------------
# Relative import resolution helper
# ---------------------------------------------------------------------------

def test_resolve_relative_import_same_package():
    result = _resolve_relative_import("models", 1, "app.routes")
    assert result == "app.models"


def test_resolve_relative_import_parent_package():
    result = _resolve_relative_import("utils", 2, "app.routes.users")
    assert result == "app.utils"


def test_resolve_relative_import_no_module():
    result = _resolve_relative_import(None, 1, "app.routes")
    assert result == "app"


def test_resolve_relative_import_top_level_overflow():
    # level > depth of package
    result = _resolve_relative_import("foo", 5, "a.b")
    assert result == "foo"


# ---------------------------------------------------------------------------
# Absolute imports
# ---------------------------------------------------------------------------

def test_absolute_import_stdlib():
    mod = _make_module("myapp.main", "import os\nimport sys\n")
    builder, warnings = _run_extractor(mod)
    doc = builder.build()

    node_names = {n.name for n in doc.nodes}
    assert "os" in node_names
    assert "sys" in node_names

    os_node = next(n for n in doc.nodes if n.name == "os")
    assert os_node.type == NodeType.EXTERNAL_MODULE
    assert os_node.certainty == Certainty.EXACT

    edge_types = {e.type for e in doc.edges}
    assert EdgeType.IMPORTS in edge_types


def test_absolute_import_creates_source_node():
    mod = _make_module("myapp.main", "import os\n")
    builder, _ = _run_extractor(mod)
    doc = builder.build()

    source_node = next((n for n in doc.nodes if n.name == "myapp.main"), None)
    assert source_node is not None
    assert source_node.type == NodeType.MODULE


def test_absolute_import_local_module():
    mod_a = _make_module("app.main", "from app.utils import greet\n")
    mod_b = _make_module("app.utils", "def greet(): pass\n")
    builder, warnings = _run_extractor(mod_a, mod_b)
    doc = builder.build()

    utils_node = next((n for n in doc.nodes if n.name == "app.utils"), None)
    assert utils_node is not None
    assert utils_node.type == NodeType.MODULE
    assert utils_node.certainty == Certainty.EXACT

    edge = next((e for e in doc.edges if e.type == EdgeType.IMPORTS_FROM), None)
    assert edge is not None
    assert edge.metadata.get("names") == "greet"


def test_absolute_import_unknown_third_party():
    mod = _make_module("myapp.main", "import requests\n")
    builder, _ = _run_extractor(mod)
    doc = builder.build()

    req_node = next((n for n in doc.nodes if n.name == "requests"), None)
    assert req_node is not None
    assert req_node.type == NodeType.EXTERNAL_MODULE
    # certainty is INFERRED since we can't confirm it's installed
    assert req_node.certainty == Certainty.INFERRED


# ---------------------------------------------------------------------------
# Relative imports
# ---------------------------------------------------------------------------

def test_relative_import_resolved():
    mod_main = _make_module("app.main", "from .utils import greet\n",
                             file_path="/proj/app/main.py")
    mod_utils = _make_module("app.utils", "def greet(): pass\n",
                              file_path="/proj/app/utils.py")
    builder, warnings = _run_extractor(mod_main, mod_utils)
    doc = builder.build()

    utils_node = next((n for n in doc.nodes if n.name == "app.utils"), None)
    assert utils_node is not None
    assert utils_node.type == NodeType.MODULE

    # No UNRESOLVABLE warnings
    unresolvable = [w for w in warnings if w.code == "UNRESOLVABLE_RELATIVE_IMPORT"]
    assert not unresolvable


def test_relative_import_at_root_level_no_crash():
    # level=4 from a top-level module "a" — the resolver clamps to root, returns the
    # module name without None. No warning is expected, but no crash either.
    mod = _make_module("a", "from ....missing import foo\n",
                        file_path="/proj/a.py")
    builder, warnings = _run_extractor(mod)
    # The import resolves (clamped) — so no UNRESOLVABLE_RELATIVE_IMPORT warning
    unresolvable = [w for w in warnings if w.code == "UNRESOLVABLE_RELATIVE_IMPORT"]
    assert not unresolvable
    # But a node for the resolved target should have been created
    doc = builder.build()
    node_names = {n.name for n in doc.nodes}
    assert any("missing" in name for name in node_names)


# ---------------------------------------------------------------------------
# Edge metadata
# ---------------------------------------------------------------------------

def test_imports_from_edge_carries_names():
    mod = _make_module("pkg.main", "from os.path import join, exists\n")
    builder, _ = _run_extractor(mod)
    doc = builder.build()

    edge = next((e for e in doc.edges if e.type == EdgeType.IMPORTS_FROM), None)
    assert edge is not None
    names = edge.metadata.get("names", "")
    assert "join" in names
    assert "exists" in names


def test_no_duplicate_edges_for_same_import():
    source = "import os\nimport os\n"
    mod = _make_module("myapp.main", source)
    builder, _ = _run_extractor(mod)
    doc = builder.build()

    imports_edges = [e for e in doc.edges if e.type == EdgeType.IMPORTS and "os" in e.display_name]
    assert len(imports_edges) == 1
