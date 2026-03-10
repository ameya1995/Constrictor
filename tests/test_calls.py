"""Tests for the call graph extractor."""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from constrictor.analysis.calls import CallGraphExtractor
from constrictor.core.models import Certainty, ScanWarning
from constrictor.core.parser import ParsedModule
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.models import EdgeType, NodeType


def _make_module(module_name: str, source: str) -> ParsedModule:
    tree = ast.parse(textwrap.dedent(source))
    return ParsedModule(
        file_path=Path(f"/fake/{module_name.replace('.', '/')}.py"),
        module_name=module_name,
        ast_tree=tree,
    )


def _run_extractor(*modules: ParsedModule) -> tuple[GraphBuilder, list[ScanWarning]]:
    builder = GraphBuilder()
    warnings: list[ScanWarning] = []
    extractor = CallGraphExtractor()
    extractor.contribute(list(modules), builder, warnings)
    return builder, warnings


# ---------------------------------------------------------------------------
# Function node creation
# ---------------------------------------------------------------------------

def test_top_level_function_creates_node():
    mod = _make_module("myapp.utils", """\
        def greet(name: str) -> str:
            return f"Hello, {name}!"
    """)
    builder, _ = _run_extractor(mod)
    doc = builder.build()

    func_nodes = [n for n in doc.nodes if n.type == NodeType.FUNCTION]
    assert any("greet" in n.qualified_name for n in func_nodes)


def test_function_contains_edge_from_module():
    mod = _make_module("myapp.utils", """\
        def helper():
            pass
    """)
    builder, _ = _run_extractor(mod)
    doc = builder.build()

    contains_edges = [e for e in doc.edges if e.type == EdgeType.CONTAINS]
    assert any("helper" in e.display_name for e in contains_edges)


# ---------------------------------------------------------------------------
# Simple call edges
# ---------------------------------------------------------------------------

def test_simple_call_creates_edge():
    mod = _make_module("myapp.main", """\
        def helper():
            pass

        def run():
            helper()
    """)
    builder, _ = _run_extractor(mod)
    doc = builder.build()

    call_edges = [e for e in doc.edges if e.type == EdgeType.CALLS]
    assert call_edges, "Expected at least one CALLS edge"
    assert any("helper" in e.display_name for e in call_edges)


def test_unresolvable_call_is_ambiguous():
    mod = _make_module("myapp.main", """\
        def run():
            unknown_function()
    """)
    builder, _ = _run_extractor(mod)
    doc = builder.build()

    call_edges = [e for e in doc.edges if e.type == EdgeType.CALLS]
    assert call_edges
    ambiguous = [e for e in call_edges if e.certainty == Certainty.AMBIGUOUS]
    assert ambiguous


# ---------------------------------------------------------------------------
# Method calls
# ---------------------------------------------------------------------------

def test_self_method_call_is_inferred():
    mod = _make_module("myapp.service", """\
        class MyService:
            def process(self):
                self.validate()

            def validate(self):
                pass
    """)
    builder, _ = _run_extractor(mod)
    doc = builder.build()

    call_edges = [e for e in doc.edges if e.type == EdgeType.CALLS]
    self_calls = [e for e in call_edges if "validate" in e.display_name]
    assert self_calls
    assert all(e.certainty == Certainty.INFERRED for e in self_calls)


# ---------------------------------------------------------------------------
# Cross-module calls
# ---------------------------------------------------------------------------

def test_cross_module_call_inferred():
    mod_main = _make_module("app.main", """\
        from app import utils

        def run():
            utils.greet("World")
    """)
    mod_utils = _make_module("app.utils", """\
        def greet(name):
            return f"Hello, {name}!"
    """)
    builder, _ = _run_extractor(mod_main, mod_utils)
    doc = builder.build()

    call_edges = [e for e in doc.edges if e.type == EdgeType.CALLS]
    assert call_edges


# ---------------------------------------------------------------------------
# Method nodes in classes
# ---------------------------------------------------------------------------

def test_method_nodes_created_in_class():
    mod = _make_module("myapp.models", """\
        class User:
            def __init__(self, name):
                self.name = name

            def greet(self):
                return f"Hello, {self.name}"
    """)
    builder, _ = _run_extractor(mod)
    doc = builder.build()

    method_nodes = [n for n in doc.nodes if n.type == NodeType.METHOD]
    method_names = {n.name for n in method_nodes}
    assert "__init__" in method_names
    assert "greet" in method_names


def test_class_contains_method_edges():
    mod = _make_module("myapp.models", """\
        class Counter:
            def increment(self):
                pass
    """)
    builder, _ = _run_extractor(mod)
    doc = builder.build()

    contains_edges = [e for e in doc.edges if e.type == EdgeType.CONTAINS]
    assert any("increment" in e.display_name for e in contains_edges)
