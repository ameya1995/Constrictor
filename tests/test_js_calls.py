"""Tests for the JS/TS call-graph extractor."""
from __future__ import annotations

import pytest

from constrictor.core.js_parser import _ensure_languages, parse_js_file
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.models import EdgeType, NodeType

pytestmark = pytest.mark.skipif(
    not _ensure_languages(),
    reason="tree-sitter JS/TS grammars not installed",
)


def _make_module(tmp_path, filename, source):
    fp = tmp_path / filename
    fp.write_text(source, encoding="utf-8")
    return parse_js_file(fp, tmp_path)


def _run_calls(module, builder=None):
    from constrictor.analysis.js_calls import JSCallExtractor

    if builder is None:
        builder = GraphBuilder()
    extractor = JSCallExtractor()
    extractor.contribute_js([module], builder, [])
    return builder


def test_function_declaration(tmp_path):
    src = "function greet() { return 'hi'; }"
    module = _make_module(tmp_path, "a.js", src)
    assert module is not None
    builder = _run_calls(module)
    fn_nodes = [n for n in builder._nodes.values() if n.type == NodeType.JS_FUNCTION]
    names = {n.name for n in fn_nodes}
    assert "greet" in names


def test_arrow_function(tmp_path):
    src = "const fetchData = () => {};"
    module = _make_module(tmp_path, "a.js", src)
    assert module is not None
    builder = _run_calls(module)
    fn_nodes = [n for n in builder._nodes.values() if n.type == NodeType.JS_FUNCTION]
    names = {n.name for n in fn_nodes}
    assert "fetchData" in names


def test_react_component_detected(tmp_path):
    src = "const UserList = () => <div/>"
    module = _make_module(tmp_path, "UserList.jsx", src)
    assert module is not None
    builder = _run_calls(module)
    component_nodes = [n for n in builder._nodes.values() if n.type == NodeType.JS_COMPONENT]
    names = {n.name for n in component_nodes}
    assert "UserList" in names


def test_class_component_detected(tmp_path):
    src = """
import React from "react";
class MyWidget extends React.Component {
  render() { return null; }
}
"""
    module = _make_module(tmp_path, "Widget.jsx", src)
    assert module is not None
    builder = _run_calls(module)
    component_nodes = [n for n in builder._nodes.values() if n.type == NodeType.JS_COMPONENT]
    names = {n.name for n in component_nodes}
    assert "MyWidget" in names


def test_method_contains_edge(tmp_path):
    src = """
class Foo {
  bar() {}
}
"""
    module = _make_module(tmp_path, "foo.js", src)
    assert module is not None
    builder = _run_calls(module)
    edges = list(builder._edges.values())
    contains_edges = [e for e in edges if e.type == EdgeType.CONTAINS]
    assert len(contains_edges) >= 1


def test_module_contains_function_edge(tmp_path):
    src = "function doWork() {}"
    module = _make_module(tmp_path, "work.js", src)
    assert module is not None
    builder = _run_calls(module)
    edges = list(builder._edges.values())
    contains_edges = [e for e in edges if e.type == EdgeType.CONTAINS]
    assert len(contains_edges) >= 1
