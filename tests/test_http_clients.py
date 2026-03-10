"""Tests for the HTTP client extractor."""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

from constrictor.analysis.http_clients import HTTPClientExtractor
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
    HTTPClientExtractor().contribute(list(modules), builder, warnings)
    return builder, warnings


# ---------------------------------------------------------------------------
# requests module detection
# ---------------------------------------------------------------------------

def test_requests_get_static_url():
    mod = _make_module("app.service", """
        import requests

        def fetch():
            return requests.get("http://example.com/api/users")
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    ep_nodes = [n for n in doc.nodes if n.type == NodeType.EXTERNAL_ENDPOINT]
    assert len(ep_nodes) == 1
    assert "example.com/api/users" in ep_nodes[0].metadata.get("url", "")
    assert ep_nodes[0].certainty == Certainty.EXACT


def test_requests_post_static_url():
    mod = _make_module("app.service", """
        import requests

        def notify():
            requests.post("http://notify.service/send", json={})
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    ep_nodes = [n for n in doc.nodes if n.type == NodeType.EXTERNAL_ENDPOINT]
    assert any("notify.service" in n.metadata.get("url", "") for n in ep_nodes)


def test_requests_dynamic_url():
    mod = _make_module("app.service", """
        import requests

        def fetch(user_id):
            return requests.get(f"http://auth-service/users/{user_id}")
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    ep_nodes = [n for n in doc.nodes if n.type == NodeType.EXTERNAL_ENDPOINT]
    assert len(ep_nodes) == 1
    assert ep_nodes[0].certainty == Certainty.AMBIGUOUS
    assert ep_nodes[0].metadata.get("url") == "<dynamic>"


def test_requests_all_methods():
    mod = _make_module("app.service", """
        import requests

        def ops():
            requests.get("http://a.com/r")
            requests.post("http://a.com/r")
            requests.put("http://a.com/r")
            requests.delete("http://a.com/r")
            requests.patch("http://a.com/r")
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    ep_nodes = [n for n in doc.nodes if n.type == NodeType.EXTERNAL_ENDPOINT]
    assert len(ep_nodes) == 5


# ---------------------------------------------------------------------------
# httpx module detection
# ---------------------------------------------------------------------------

def test_httpx_get_static_url():
    mod = _make_module("app.service", """
        import httpx

        def fetch():
            return httpx.get("https://api.remote.io/data")
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    ep_nodes = [n for n in doc.nodes if n.type == NodeType.EXTERNAL_ENDPOINT]
    assert len(ep_nodes) == 1
    assert "api.remote.io" in ep_nodes[0].metadata.get("url", "")


# ---------------------------------------------------------------------------
# Session-based calls
# ---------------------------------------------------------------------------

def test_requests_session_get():
    mod = _make_module("app.service", """
        import requests

        def fetch():
            return requests.Session().get("http://session.example.com/data")
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    ep_nodes = [n for n in doc.nodes if n.type == NodeType.EXTERNAL_ENDPOINT]
    assert len(ep_nodes) == 1


def test_httpx_client_post():
    mod = _make_module("app.service", """
        import httpx

        def send():
            httpx.Client().post("http://payment.service/charge", json={})
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    ep_nodes = [n for n in doc.nodes if n.type == NodeType.EXTERNAL_ENDPOINT]
    assert len(ep_nodes) == 1


# ---------------------------------------------------------------------------
# CALLS_HTTP edges
# ---------------------------------------------------------------------------

def test_calls_http_edge_created():
    mod = _make_module("app.service", """
        import requests

        def fetch():
            requests.get("http://example.com/")
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    edges = [e for e in doc.edges if e.type == EdgeType.CALLS_HTTP]
    assert len(edges) == 1


def test_caller_function_node_created():
    mod = _make_module("app.service", """
        import requests

        def fetch_users():
            requests.get("http://api.example.com/users")
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    func_nodes = [n for n in doc.nodes if n.type == NodeType.FUNCTION]
    assert any("fetch_users" in n.qualified_name for n in func_nodes)


# ---------------------------------------------------------------------------
# Non-http calls are ignored
# ---------------------------------------------------------------------------

def test_non_http_call_ignored():
    mod = _make_module("app.utils", """
        import json

        def load():
            return json.loads("{}")
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    ep_nodes = [n for n in doc.nodes if n.type == NodeType.EXTERNAL_ENDPOINT]
    assert len(ep_nodes) == 0
