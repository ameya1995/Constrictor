"""Tests for the Constrictor web API."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from constrictor.core.models import Certainty
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.models import EdgeType, NodeType
from constrictor.web.app import create_app


# ─── Fixture: shared test document + client ───────────────────────────────


def _build_test_doc():
    builder = GraphBuilder()
    builder.add_node(
        "mod:main",
        NodeType.MODULE,
        "app.main",
        qualified_name="app.main",
        display_name="app.main",
        file_path="app/main.py",
    )
    builder.add_node(
        "func:greet",
        NodeType.FUNCTION,
        "greet",
        qualified_name="app.utils.greet",
        display_name="greet",
        file_path="app/utils.py",
    )
    builder.add_node(
        "cls:user",
        NodeType.CLASS,
        "User",
        qualified_name="app.models.User",
        display_name="User",
        file_path="app/models.py",
    )
    builder.add_node(
        "svc:api",
        NodeType.SERVICE,
        "api",
        qualified_name="api",
        display_name="api",
        metadata={"endpoints": "[]"},
    )
    builder.add_edge(
        "mod:main",
        "func:greet",
        EdgeType.CALLS,
        display_name="main -> greet",
        certainty=Certainty.EXACT,
    )
    builder.add_edge(
        "mod:main",
        "cls:user",
        EdgeType.IMPORTS,
        display_name="main imports User",
        certainty=Certainty.AMBIGUOUS,
    )
    builder.add_edge(
        "mod:main",
        "svc:api",
        EdgeType.BELONGS_TO_SERVICE,
        display_name="main belongs to api",
        certainty=Certainty.EXACT,
    )
    return builder.build(scan_metadata=None, warnings=[])


@pytest.fixture(scope="module")
def client():
    doc = _build_test_doc()
    app = create_app(doc)
    return TestClient(app)


# ─── GET /api/summary ─────────────────────────────────────────────────────


def test_summary_ok(client):
    resp = client.get("/api/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "statistics" in data
    assert "scan_metadata" in data


def test_summary_has_node_count(client):
    resp = client.get("/api/summary")
    stats = resp.json()["statistics"]
    assert stats["total_nodes"] >= 4


def test_summary_scan_metadata_none(client):
    resp = client.get("/api/summary")
    assert resp.json()["scan_metadata"] is None


# ─── GET /api/nodes ───────────────────────────────────────────────────────


def test_nodes_returns_all(client):
    resp = client.get("/api/nodes")
    assert resp.status_code == 200
    nodes = resp.json()
    assert len(nodes) >= 4


def test_nodes_filter_by_type(client):
    resp = client.get("/api/nodes?type=FUNCTION")
    assert resp.status_code == 200
    nodes = resp.json()
    assert all(n["type"] == "FUNCTION" for n in nodes)
    assert any(n["id"] == "func:greet" for n in nodes)


def test_nodes_filter_multiple_types(client):
    resp = client.get("/api/nodes?type=FUNCTION&type=CLASS")
    assert resp.status_code == 200
    nodes = resp.json()
    types = {n["type"] for n in nodes}
    assert types <= {"FUNCTION", "CLASS"}


def test_nodes_filter_no_match(client):
    resp = client.get("/api/nodes?type=TABLE")
    assert resp.status_code == 200
    assert resp.json() == []


def test_nodes_have_required_fields(client):
    resp = client.get("/api/nodes")
    for n in resp.json():
        assert "id" in n
        assert "type" in n
        assert "display_name" in n
        assert "qualified_name" in n


# ─── GET /api/edges ───────────────────────────────────────────────────────


def test_edges_returns_all(client):
    resp = client.get("/api/edges")
    assert resp.status_code == 200
    edges = resp.json()
    assert len(edges) >= 3


def test_edges_filter_by_type(client):
    resp = client.get("/api/edges?type=CALLS")
    assert resp.status_code == 200
    edges = resp.json()
    assert all(e["type"] == "CALLS" for e in edges)


def test_edges_filter_multiple_types(client):
    resp = client.get("/api/edges?type=CALLS&type=IMPORTS")
    assert resp.status_code == 200
    edges = resp.json()
    types = {e["type"] for e in edges}
    assert types <= {"CALLS", "IMPORTS"}


def test_edges_have_required_fields(client):
    resp = client.get("/api/edges")
    for e in resp.json():
        assert "id" in e
        assert "source_id" in e
        assert "target_id" in e
        assert "type" in e


# ─── GET /api/impact ──────────────────────────────────────────────────────


def test_impact_downstream_ok(client):
    resp = client.get("/api/impact?node=mod%3Amain&direction=downstream&depth=6")
    assert resp.status_code == 200
    data = resp.json()
    assert "focus_node" in data
    assert data["focus_node"]["id"] == "mod:main"


def test_impact_upstream_ok(client):
    resp = client.get("/api/impact?node=func%3Agreet&direction=upstream&depth=6")
    assert resp.status_code == 200
    data = resp.json()
    assert data["focus_node"]["id"] == "func:greet"


def test_impact_not_found(client):
    resp = client.get("/api/impact?node=does_not_exist")
    assert resp.status_code == 404


def test_impact_invalid_direction(client):
    resp = client.get("/api/impact?node=mod%3Amain&direction=sideways")
    assert resp.status_code == 400


def test_impact_has_nodes_and_edges(client):
    resp = client.get("/api/impact?node=mod%3Amain&direction=downstream")
    data = resp.json()
    assert isinstance(data["nodes"], list)
    assert isinstance(data["edges"], list)


# ─── GET /api/paths ───────────────────────────────────────────────────────


def test_paths_ok(client):
    resp = client.get("/api/paths?from=mod%3Amain&to=func%3Agreet&depth=8")
    assert resp.status_code == 200
    data = resp.json()
    assert "from_node" in data
    assert "to_node" in data
    assert "paths" in data


def test_paths_from_not_found(client):
    resp = client.get("/api/paths?from=no_such_node&to=func%3Agreet")
    assert resp.status_code == 404


def test_paths_to_not_found(client):
    resp = client.get("/api/paths?from=mod%3Amain&to=no_such_node")
    assert resp.status_code == 404


def test_paths_no_path_between_nodes(client):
    # func:greet -> mod:main has no path (one-directional)
    resp = client.get("/api/paths?from=func%3Agreet&to=svc%3Aapi")
    assert resp.status_code == 200
    data = resp.json()
    # Zero paths is fine
    assert isinstance(data["paths"], list)


# ─── GET /api/services ────────────────────────────────────────────────────


def test_services_ok(client):
    resp = client.get("/api/services")
    assert resp.status_code == 200
    services = resp.json()
    assert isinstance(services, list)
    assert any(s["id"] == "svc:api" for s in services)


def test_services_only_service_types(client):
    resp = client.get("/api/services")
    for s in resp.json():
        assert s["type"] in ("SERVICE", "COMPONENT")


# ─── GET / (root) ─────────────────────────────────────────────────────────


def test_root_returns_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
