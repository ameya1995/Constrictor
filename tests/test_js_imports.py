"""Tests for the JS/TS import extractor."""
from __future__ import annotations

import pytest

from constrictor.core.js_parser import _ensure_languages, parse_js_file
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.models import EdgeType, NodeType

pytestmark = pytest.mark.skipif(
    not _ensure_languages(),
    reason="tree-sitter JS/TS grammars not installed",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_module(tmp_path, filename: str, source: str):
    fp = tmp_path / filename
    fp.write_text(source, encoding="utf-8")
    return parse_js_file(fp, tmp_path)


def _run_imports(module, builder=None):
    from constrictor.analysis.js_imports import JSImportExtractor

    if builder is None:
        builder = GraphBuilder()
    extractor = JSImportExtractor()
    extractor.contribute_js([module], builder, [])
    return builder


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_default_import(tmp_path):
    module = _make_module(tmp_path, "a.js", 'import React from "react";')
    assert module is not None
    builder = _run_imports(module)
    node_names = {n.qualified_name for n in builder._nodes.values()}
    assert "react" in node_names


def test_named_import(tmp_path):
    module = _make_module(tmp_path, "a.js", 'import { useState } from "react";')
    assert module is not None
    builder = _run_imports(module)
    edges = list(builder._edges.values())
    assert any(e.type == EdgeType.IMPORTS_FROM for e in edges)


def test_local_relative_import(tmp_path):
    module = _make_module(tmp_path, "a.js", 'import utils from "./utils";')
    assert module is not None
    builder = _run_imports(module)
    node_names = {n.qualified_name for n in builder._nodes.values()}
    # Should have a JS_MODULE node whose name ends with "utils"
    assert any("utils" in name for name in node_names)


def test_require_call(tmp_path):
    module = _make_module(tmp_path, "a.js", 'const _ = require("lodash");')
    assert module is not None
    builder = _run_imports(module)
    node_names = {n.qualified_name for n in builder._nodes.values()}
    assert "lodash" in node_names
    edges = list(builder._edges.values())
    assert any(e.type == EdgeType.IMPORTS for e in edges)


def test_source_module_node_created(tmp_path):
    module = _make_module(tmp_path, "foo.js", 'import x from "bar";')
    assert module is not None
    builder = _run_imports(module)
    js_modules = [n for n in builder._nodes.values() if n.type == NodeType.JS_MODULE]
    source_names = {n.qualified_name for n in js_modules}
    assert "foo" in source_names


def test_typescript_import(tmp_path):
    module = _make_module(tmp_path, "comp.ts", 'import { useSWR } from "swr";')
    assert module is not None
    builder = _run_imports(module)
    node_names = {n.qualified_name for n in builder._nodes.values()}
    assert "swr" in node_names
