"""Tests for the class hierarchy extractor."""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from constrictor.analysis.classes import ClassHierarchyExtractor
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
    extractor = ClassHierarchyExtractor()
    extractor.contribute(list(modules), builder, warnings)
    return builder, warnings


# ---------------------------------------------------------------------------
# Basic class creation
# ---------------------------------------------------------------------------

def test_simple_class_creates_node():
    mod = _make_module("myapp.models", """\
        class User:
            pass
    """)
    builder, _ = _run_extractor(mod)
    doc = builder.build()

    class_nodes = [n for n in doc.nodes if n.type == NodeType.CLASS]
    assert any("User" in n.name for n in class_nodes)


def test_class_contains_edge_from_module():
    mod = _make_module("myapp.models", """\
        class Product:
            pass
    """)
    builder, _ = _run_extractor(mod)
    doc = builder.build()

    contains = [e for e in doc.edges if e.type == EdgeType.CONTAINS]
    assert any("Product" in e.display_name for e in contains)


# ---------------------------------------------------------------------------
# Single inheritance
# ---------------------------------------------------------------------------

def test_single_inheritance_creates_inherits_edge():
    mod = _make_module("myapp.models", """\
        class Base:
            pass

        class Child(Base):
            pass
    """)
    builder, _ = _run_extractor(mod)
    doc = builder.build()

    inherits_edges = [e for e in doc.edges if e.type == EdgeType.INHERITS]
    assert inherits_edges, "Expected INHERITS edge"
    assert any("Base" in e.display_name for e in inherits_edges)


# ---------------------------------------------------------------------------
# Multiple inheritance
# ---------------------------------------------------------------------------

def test_multiple_inheritance():
    mod = _make_module("myapp.mixins", """\
        class Mixin:
            pass

        class Base:
            pass

        class Combined(Base, Mixin):
            pass
    """)
    builder, _ = _run_extractor(mod)
    doc = builder.build()

    inherits_edges = [e for e in doc.edges if e.type == EdgeType.INHERITS]
    assert len(inherits_edges) >= 2


# ---------------------------------------------------------------------------
# ABC / Protocol -> IMPLEMENTS
# ---------------------------------------------------------------------------

def test_abc_base_creates_implements_edge():
    mod = _make_module("myapp.abc_test", """\
        from abc import ABC

        class MyABC(ABC):
            pass
    """)
    builder, _ = _run_extractor(mod)
    doc = builder.build()

    implements_edges = [e for e in doc.edges if e.type == EdgeType.IMPLEMENTS]
    assert implements_edges, "Expected IMPLEMENTS edge for ABC subclass"


def test_protocol_base_creates_implements_edge():
    mod = _make_module("myapp.proto", """\
        from typing import Protocol

        class MyProtocol(Protocol):
            pass
    """)
    builder, _ = _run_extractor(mod)
    doc = builder.build()

    implements_edges = [e for e in doc.edges if e.type == EdgeType.IMPLEMENTS]
    assert implements_edges, "Expected IMPLEMENTS edge for Protocol subclass"


# ---------------------------------------------------------------------------
# Methods
# ---------------------------------------------------------------------------

def test_methods_extracted_with_contains_edges():
    mod = _make_module("myapp.service", """\
        class UserService:
            def __init__(self):
                pass

            def create_user(self, name):
                pass

            def delete_user(self, user_id):
                pass
    """)
    builder, _ = _run_extractor(mod)
    doc = builder.build()

    method_nodes = [n for n in doc.nodes if n.type == NodeType.METHOD]
    method_names = {n.name for n in method_nodes}
    assert "__init__" in method_names
    assert "create_user" in method_names
    assert "delete_user" in method_names

    contains_edges = [e for e in doc.edges if e.type == EdgeType.CONTAINS]
    assert any("create_user" in e.display_name for e in contains_edges)


# ---------------------------------------------------------------------------
# Nested classes
# ---------------------------------------------------------------------------

def test_nested_class_creates_contains_edge():
    mod = _make_module("myapp.config", """\
        class Config:
            class Meta:
                abstract = True
    """)
    builder, _ = _run_extractor(mod)
    doc = builder.build()

    class_nodes = [n for n in doc.nodes if n.type == NodeType.CLASS]
    class_names = {n.name for n in class_nodes}
    assert "Config" in class_names
    assert "Meta" in class_names

    contains_edges = [e for e in doc.edges if e.type == EdgeType.CONTAINS]
    assert any("Meta" in e.display_name for e in contains_edges)


# ---------------------------------------------------------------------------
# Cross-module inheritance
# ---------------------------------------------------------------------------

def test_cross_module_inheritance_inferred():
    mod_base = _make_module("myapp.base", """\
        class BaseModel:
            pass
    """)
    mod_child = _make_module("myapp.models", """\
        from myapp.base import BaseModel

        class User(BaseModel):
            pass
    """)
    builder, _ = _run_extractor(mod_base, mod_child)
    doc = builder.build()

    inherits_edges = [e for e in doc.edges if e.type == EdgeType.INHERITS]
    assert inherits_edges
    # Cross-module inheritance resolution is INFERRED (from-import lookup)
    base_edge = next(
        (e for e in inherits_edges if "BaseModel" in e.display_name), None
    )
    assert base_edge is not None
    assert base_edge.certainty in (Certainty.INFERRED, Certainty.EXACT)
