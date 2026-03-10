"""Tests for the Flask extractor."""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

from constrictor.analysis.flask import FlaskExtractor
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
    FlaskExtractor().contribute(list(modules), builder, warnings)
    return builder, warnings


# ---------------------------------------------------------------------------
# Basic @app.route detection
# ---------------------------------------------------------------------------

def test_simple_get_route():
    mod = _make_module("app.views", """
        from flask import Flask
        app = Flask(__name__)

        @app.route("/hello")
        def hello(): pass
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    ep_nodes = [n for n in doc.nodes if n.type == NodeType.ENDPOINT]
    assert len(ep_nodes) == 1
    assert ep_nodes[0].display_name == "GET /hello"
    assert ep_nodes[0].metadata["http_method"] == "GET"
    assert ep_nodes[0].metadata["path"] == "/hello"


def test_route_with_explicit_get_method():
    mod = _make_module("app.views", """
        from flask import Flask
        app = Flask(__name__)

        @app.route("/users", methods=["GET"])
        def list_users(): pass
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    ep_nodes = [n for n in doc.nodes if n.type == NodeType.ENDPOINT]
    assert any(n.display_name == "GET /users" for n in ep_nodes)


def test_route_multiple_methods():
    mod = _make_module("app.views", """
        from flask import Flask
        app = Flask(__name__)

        @app.route("/items", methods=["GET", "POST"])
        def items(): pass
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    ep_nodes = [n for n in doc.nodes if n.type == NodeType.ENDPOINT]
    assert len(ep_nodes) == 2
    method_names = {n.display_name for n in ep_nodes}
    assert "GET /items" in method_names
    assert "POST /items" in method_names


def test_route_put_delete_methods():
    mod = _make_module("app.views", """
        from flask import Flask
        app = Flask(__name__)

        @app.route("/resource/<int:id>", methods=["PUT", "DELETE"])
        def update_or_delete(id): pass
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    ep_nodes = [n for n in doc.nodes if n.type == NodeType.ENDPOINT]
    assert len(ep_nodes) == 2


# ---------------------------------------------------------------------------
# Blueprint routes
# ---------------------------------------------------------------------------

def test_blueprint_route():
    mod = _make_module("app.products", """
        from flask import Blueprint
        bp = Blueprint("products", __name__)

        @bp.route("/products")
        def list_products(): pass
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    ep_nodes = [n for n in doc.nodes if n.type == NodeType.ENDPOINT]
    assert len(ep_nodes) == 1
    assert ep_nodes[0].display_name == "GET /products"


# ---------------------------------------------------------------------------
# EXPOSES_ENDPOINT edges
# ---------------------------------------------------------------------------

def test_exposes_endpoint_edge_created():
    mod = _make_module("app.views", """
        from flask import Flask
        app = Flask(__name__)

        @app.route("/health")
        def health(): pass
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    edges = [e for e in doc.edges if e.type == EdgeType.EXPOSES_ENDPOINT]
    assert len(edges) == 1


def test_multiple_routes_multiple_edges():
    mod = _make_module("app.views", """
        from flask import Flask
        app = Flask(__name__)

        @app.route("/a")
        def a(): pass

        @app.route("/b", methods=["GET", "POST"])
        def b(): pass
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    ep_nodes = [n for n in doc.nodes if n.type == NodeType.ENDPOINT]
    assert len(ep_nodes) == 3  # /a GET, /b GET, /b POST

    edges = [e for e in doc.edges if e.type == EdgeType.EXPOSES_ENDPOINT]
    assert len(edges) == 3


# ---------------------------------------------------------------------------
# Non-route decorators are ignored
# ---------------------------------------------------------------------------

def test_non_route_decorator_not_detected():
    mod = _make_module("app.tasks", """
        def before_request(f): return f

        @before_request
        def setup(): pass
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    ep_nodes = [n for n in doc.nodes if n.type == NodeType.ENDPOINT]
    assert len(ep_nodes) == 0
