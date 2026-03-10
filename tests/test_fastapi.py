"""Tests for the FastAPI extractor."""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

from constrictor.analysis.fastapi import FastAPIExtractor
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


def _run(*modules: ParsedModule) -> tuple[GraphBuilder, list[ScanWarning]]:
    builder = GraphBuilder()
    warnings: list[ScanWarning] = []
    FastAPIExtractor().contribute(list(modules), builder, warnings)
    return builder, warnings


# ---------------------------------------------------------------------------
# Basic route detection
# ---------------------------------------------------------------------------

def test_get_route_creates_endpoint_node():
    mod = _make_module("app.routes", """
        from fastapi import APIRouter
        router = APIRouter()

        @router.get("/items")
        def list_items():
            return []
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    ep_nodes = [n for n in doc.nodes if n.type == NodeType.ENDPOINT]
    assert len(ep_nodes) == 1
    assert ep_nodes[0].display_name == "GET /items"
    assert ep_nodes[0].metadata["http_method"] == "GET"
    assert ep_nodes[0].metadata["path"] == "/items"


def test_post_route():
    mod = _make_module("app.routes", """
        from fastapi import APIRouter
        router = APIRouter()

        @router.post("/items")
        def create_item():
            pass
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    ep_nodes = [n for n in doc.nodes if n.type == NodeType.ENDPOINT]
    assert any(n.display_name == "POST /items" for n in ep_nodes)


def test_delete_route():
    mod = _make_module("app.routes", """
        from fastapi import APIRouter
        router = APIRouter()

        @router.delete("/items/{item_id}")
        def delete_item(item_id: int):
            pass
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    ep_nodes = [n for n in doc.nodes if n.type == NodeType.ENDPOINT]
    assert any("DELETE" in n.display_name for n in ep_nodes)


def test_multiple_routes_multiple_endpoints():
    mod = _make_module("app.routes", """
        from fastapi import APIRouter
        router = APIRouter()

        @router.get("/a")
        def get_a(): pass

        @router.post("/b")
        def post_b(): pass

        @router.put("/c")
        def put_c(): pass
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    ep_nodes = [n for n in doc.nodes if n.type == NodeType.ENDPOINT]
    assert len(ep_nodes) == 3


def test_exposes_endpoint_edge():
    mod = _make_module("app.routes", """
        from fastapi import APIRouter
        router = APIRouter()

        @router.get("/users")
        def list_users(): pass
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    edges = [e for e in doc.edges if e.type == EdgeType.EXPOSES_ENDPOINT]
    assert len(edges) == 1


# ---------------------------------------------------------------------------
# Depends() injection
# ---------------------------------------------------------------------------

def test_depends_creates_inject_dependency_edge():
    mod = _make_module("app.routes", """
        from fastapi import APIRouter, Depends
        router = APIRouter()

        def get_db():
            pass

        @router.get("/items")
        def list_items(db=Depends(get_db)):
            return []
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    dep_edges = [e for e in doc.edges if e.type == EdgeType.INJECTS_DEPENDENCY]
    assert len(dep_edges) >= 1


def test_multiple_depends():
    mod = _make_module("app.routes", """
        from fastapi import APIRouter, Depends
        router = APIRouter()

        def get_db(): pass
        def get_user(): pass

        @router.get("/me")
        def me(db=Depends(get_db), user=Depends(get_user)):
            pass
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    dep_edges = [e for e in doc.edges if e.type == EdgeType.INJECTS_DEPENDENCY]
    assert len(dep_edges) >= 2


# ---------------------------------------------------------------------------
# Type annotation edges
# ---------------------------------------------------------------------------

def test_pydantic_model_param_creates_type_annotated_edge():
    user_mod = _make_module("app.models", """
        from pydantic import BaseModel
        class UserCreate(BaseModel):
            name: str
    """)
    routes_mod = _make_module("app.routes", """
        from fastapi import APIRouter
        router = APIRouter()

        @router.post("/users")
        def create_user(body: UserCreate): pass
    """)
    builder, _ = _run(user_mod, routes_mod)
    doc = builder.build()

    ta_edges = [e for e in doc.edges if e.type == EdgeType.TYPE_ANNOTATED]
    assert len(ta_edges) >= 1


def test_return_type_annotation_edge():
    user_mod = _make_module("app.models", """
        class UserResponse:
            pass
    """)
    routes_mod = _make_module("app.routes", """
        from fastapi import APIRouter
        router = APIRouter()

        @router.get("/users")
        def list_users() -> UserResponse: pass
    """)
    builder, _ = _run(user_mod, routes_mod)
    doc = builder.build()

    ta_edges = [e for e in doc.edges if e.type == EdgeType.TYPE_ANNOTATED]
    assert len(ta_edges) >= 1


# ---------------------------------------------------------------------------
# Non-route decorators are ignored
# ---------------------------------------------------------------------------

def test_non_route_decorator_ignored():
    mod = _make_module("app.tasks", """
        def my_decorator(f): return f

        @my_decorator
        def do_something(): pass
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    ep_nodes = [n for n in doc.nodes if n.type == NodeType.ENDPOINT]
    assert len(ep_nodes) == 0
