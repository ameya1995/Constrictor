"""Tests for the type annotation extractor."""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

from constrictor.analysis.type_annotations import TypeAnnotationExtractor, _unwrap_annotation
from constrictor.core.models import ScanWarning
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


def _run(*modules: ParsedModule) -> tuple[GraphBuilder, list[ScanWarning]]:
    builder = GraphBuilder()
    warnings: list[ScanWarning] = []
    TypeAnnotationExtractor().contribute(list(modules), builder, warnings)
    return builder, warnings


# ---------------------------------------------------------------------------
# _unwrap_annotation helper
# ---------------------------------------------------------------------------

def _parse_annotation(source: str) -> ast.expr:
    tree = ast.parse(f"x: {source}")
    return tree.body[0].annotation  # type: ignore[attr-defined]


def test_unwrap_simple_name():
    ann = _parse_annotation("User")
    names = _unwrap_annotation(ann)
    assert "User" in names


def test_unwrap_optional():
    ann = _parse_annotation("Optional[User]")
    names = _unwrap_annotation(ann)
    assert "User" in names


def test_unwrap_list():
    ann = _parse_annotation("list[User]")
    names = _unwrap_annotation(ann)
    assert "User" in names


def test_unwrap_union():
    ann = _parse_annotation("Union[User, Order]")
    names = _unwrap_annotation(ann)
    assert "User" in names
    assert "Order" in names


def test_unwrap_pep604_union():
    ann = _parse_annotation("User | None")
    names = _unwrap_annotation(ann)
    assert "User" in names


def test_unwrap_nested():
    ann = _parse_annotation("Optional[list[User]]")
    names = _unwrap_annotation(ann)
    assert "User" in names


def test_unwrap_forward_reference():
    ann = _parse_annotation('"UserModel"')
    names = _unwrap_annotation(ann)
    assert "UserModel" in names


def test_wrapper_types_not_returned():
    ann = _parse_annotation("Optional[User]")
    names = _unwrap_annotation(ann)
    assert "Optional" not in names


# ---------------------------------------------------------------------------
# Parameter type annotation -> TYPE_ANNOTATED edge
# ---------------------------------------------------------------------------

def test_param_annotation_creates_edge():
    model_mod = _make_module("app.models", """
        class UserCreate:
            pass
    """)
    routes_mod = _make_module("app.routes", """
        def create_user(body: UserCreate) -> None:
            pass
    """)
    builder, _ = _run(model_mod, routes_mod)
    doc = builder.build()

    ta_edges = [e for e in doc.edges if e.type == EdgeType.TYPE_ANNOTATED]
    assert len(ta_edges) >= 1


def test_return_annotation_creates_edge():
    model_mod = _make_module("app.models", """
        class UserResponse:
            pass
    """)
    routes_mod = _make_module("app.routes", """
        def get_user() -> UserResponse:
            pass
    """)
    builder, _ = _run(model_mod, routes_mod)
    doc = builder.build()

    ta_edges = [e for e in doc.edges if e.type == EdgeType.TYPE_ANNOTATED]
    assert len(ta_edges) >= 1


def test_optional_param_annotation():
    model_mod = _make_module("app.models", """
        class Config:
            pass
    """)
    service_mod = _make_module("app.service", """
        from typing import Optional

        def process(config: Optional[Config] = None) -> None:
            pass
    """)
    builder, _ = _run(model_mod, service_mod)
    doc = builder.build()

    ta_edges = [e for e in doc.edges if e.type == EdgeType.TYPE_ANNOTATED]
    assert len(ta_edges) >= 1


def test_list_param_annotation():
    model_mod = _make_module("app.models", """
        class Item:
            pass
    """)
    service_mod = _make_module("app.service", """
        def bulk_create(items: list[Item]) -> None:
            pass
    """)
    builder, _ = _run(model_mod, service_mod)
    doc = builder.build()

    ta_edges = [e for e in doc.edges if e.type == EdgeType.TYPE_ANNOTATED]
    assert len(ta_edges) >= 1


def test_union_annotation_creates_edges_for_each_type():
    model_mod = _make_module("app.models", """
        class Cat:
            pass

        class Dog:
            pass
    """)
    service_mod = _make_module("app.service", """
        from typing import Union

        def process(animal: Union[Cat, Dog]) -> None:
            pass
    """)
    builder, _ = _run(model_mod, service_mod)
    doc = builder.build()

    ta_edges = [e for e in doc.edges if e.type == EdgeType.TYPE_ANNOTATED]
    assert len(ta_edges) >= 2


# ---------------------------------------------------------------------------
# Annotated assignments
# ---------------------------------------------------------------------------

def test_annotated_assignment_creates_edge():
    model_mod = _make_module("app.models", """
        class Settings:
            pass
    """)
    config_mod = _make_module("app.config", """
        config: Settings
    """)
    builder, _ = _run(model_mod, config_mod)
    doc = builder.build()

    ta_edges = [e for e in doc.edges if e.type == EdgeType.TYPE_ANNOTATED]
    assert len(ta_edges) >= 1


# ---------------------------------------------------------------------------
# Unknown types are ignored
# ---------------------------------------------------------------------------

def test_unknown_type_does_not_create_edge():
    mod = _make_module("app.service", """
        def process(value: int) -> str:
            pass
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    ta_edges = [e for e in doc.edges if e.type == EdgeType.TYPE_ANNOTATED]
    assert len(ta_edges) == 0


def test_no_annotation_no_edge():
    mod = _make_module("app.service", """
        def process(value):
            pass
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    ta_edges = [e for e in doc.edges if e.type == EdgeType.TYPE_ANNOTATED]
    assert len(ta_edges) == 0
