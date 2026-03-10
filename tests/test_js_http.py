"""Tests for the JS/TS HTTP call extractor and cross-language stitching."""
from __future__ import annotations

from pathlib import Path

import pytest

from constrictor.core.js_parser import _ensure_languages, parse_js_file
from constrictor.core.models import Certainty, ScanOptions
from constrictor.core.orchestrator import run_scan
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.id_factory import create_id
from constrictor.graph.models import EdgeType, NodeType

pytestmark = pytest.mark.skipif(
    not _ensure_languages(),
    reason="tree-sitter JS/TS grammars not installed",
)

_FIXTURE = Path(__file__).parent / "fixtures" / "fullstack_js_project"


def _make_module(tmp_path, filename, source):
    fp = tmp_path / filename
    fp.write_text(source, encoding="utf-8")
    return parse_js_file(fp, tmp_path)


def _run_http(module, builder=None):
    from constrictor.analysis.js_http import JSHttpExtractor

    if builder is None:
        builder = GraphBuilder()
    extractor = JSHttpExtractor()
    extractor.contribute_js([module], builder, [])
    return builder, extractor


# ---------------------------------------------------------------------------
# fetch() detection
# ---------------------------------------------------------------------------

def test_fetch_static_url(tmp_path):
    src = """
function getUsers() {
  fetch("/api/users");
}
"""
    module = _make_module(tmp_path, "a.js", src)
    assert module is not None
    builder, _ = _run_http(module)
    ep_nodes = [n for n in builder._nodes.values() if n.type == NodeType.EXTERNAL_ENDPOINT]
    assert any("/api/users" in n.metadata.get("url", "") for n in ep_nodes)


def test_fetch_dynamic_url_is_ambiguous(tmp_path):
    src = """
function getUser(id) {
  fetch(`/api/users/${id}`);
}
"""
    module = _make_module(tmp_path, "a.js", src)
    assert module is not None
    builder, _ = _run_http(module)
    edges = [e for e in builder._edges.values() if e.type == EdgeType.CALLS_HTTP]
    assert any(e.certainty == Certainty.AMBIGUOUS for e in edges)


# ---------------------------------------------------------------------------
# axios detection
# ---------------------------------------------------------------------------

def test_axios_get(tmp_path):
    src = """
import axios from "axios";
async function fetchOrders() {
  const resp = await axios.get("/api/orders");
}
"""
    module = _make_module(tmp_path, "a.ts", src)
    assert module is not None
    builder, _ = _run_http(module)
    ep_nodes = [n for n in builder._nodes.values() if n.type == NodeType.EXTERNAL_ENDPOINT]
    assert any("/api/orders" in n.metadata.get("url", "") for n in ep_nodes)


def test_axios_post(tmp_path):
    src = """
import axios from "axios";
async function createUser(data) {
  await axios.post("/api/users", data);
}
"""
    module = _make_module(tmp_path, "a.ts", src)
    assert module is not None
    builder, _ = _run_http(module)
    ep_nodes = [n for n in builder._nodes.values() if n.type == NodeType.EXTERNAL_ENDPOINT]
    methods = {n.metadata.get("http_method") for n in ep_nodes}
    assert "POST" in methods


# ---------------------------------------------------------------------------
# useSWR detection
# ---------------------------------------------------------------------------

def test_useswr(tmp_path):
    src = """
import useSWR from "swr";
function useUsers() {
  const { data } = useSWR("/api/users");
}
"""
    module = _make_module(tmp_path, "hook.ts", src)
    assert module is not None
    builder, _ = _run_http(module)
    ep_nodes = [n for n in builder._nodes.values() if n.type == NodeType.EXTERNAL_ENDPOINT]
    assert any("/api/users" in n.metadata.get("url", "") for n in ep_nodes)


# ---------------------------------------------------------------------------
# Cross-language stitching
# ---------------------------------------------------------------------------

def test_cross_language_stitching(tmp_path):
    """A CALLS_HTTP JS edge should be stitched to a Python ENDPOINT node."""
    from constrictor.analysis.js_http import JSHttpExtractor
    from constrictor.graph.models import Certainty as C

    builder = GraphBuilder()

    # Manually add a Python ENDPOINT node (simulates FastAPI extractor output)
    ep_node_id = create_id("endpoint", "GET", "/api/users")
    builder.add_node(
        id=ep_node_id,
        type=NodeType.ENDPOINT,
        name="GET /api/users",
        qualified_name="GET /api/users",
        display_name="GET /api/users",
        file_path="backend/routes/users.py",
        certainty=C.EXACT,
        metadata={"http_method": "GET", "path": "/api/users"},
    )

    # Simulate a JS HTTP call
    src = 'async function fetchUsers() { fetch("/api/users"); }'
    module = _make_module(tmp_path, "a.js", src)
    assert module is not None
    extractor = JSHttpExtractor()
    extractor.contribute_js([module], builder, [])

    # Run post_process (cross-language stitching)
    extractor.post_process(builder)

    # Should have a stitched CALLS_HTTP edge from JS function to backend ENDPOINT
    stitched_edges = [
        e for e in builder._edges.values()
        if e.type == EdgeType.CALLS_HTTP
        and e.target_id == ep_node_id
        and e.metadata.get("stitched") == "true"
    ]
    assert len(stitched_edges) >= 1


# ---------------------------------------------------------------------------
# End-to-end fixture scan
# ---------------------------------------------------------------------------

def test_fullstack_scan_produces_js_nodes():
    """Full scan of the fullstack_js_project fixture with --include-js."""
    options = ScanOptions(root_path=_FIXTURE, include_js=True)
    document = run_scan(options)

    js_node_types = {NodeType.JS_MODULE, NodeType.JS_FUNCTION, NodeType.JS_COMPONENT}
    js_nodes = [n for n in document.nodes if n.type in js_node_types]
    assert len(js_nodes) > 0, "Expected JS nodes from frontend files"


def test_fullstack_scan_produces_calls_http_edges():
    """Full scan should produce CALLS_HTTP edges from frontend."""
    options = ScanOptions(root_path=_FIXTURE, include_js=True)
    document = run_scan(options)

    http_edges = [e for e in document.edges if e.type == EdgeType.CALLS_HTTP]
    assert len(http_edges) > 0, "Expected CALLS_HTTP edges from frontend files"


def test_fullstack_scan_stitches_to_python_endpoints():
    """Cross-language stitching should produce at least one stitched edge to a backend ENDPOINT."""
    options = ScanOptions(root_path=_FIXTURE, include_js=True)
    document = run_scan(options)

    stitched = [
        e for e in document.edges
        if e.type == EdgeType.CALLS_HTTP and e.metadata.get("stitched") == "true"
    ]
    assert len(stitched) >= 1, (
        "Expected at least one stitched cross-language CALLS_HTTP edge. "
        f"CALLS_HTTP edges found: {[e.display_name for e in document.edges if e.type == EdgeType.CALLS_HTTP]}"
    )
