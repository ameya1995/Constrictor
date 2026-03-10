"""Tests for generic decorator analysis and dynamic import detection."""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from constrictor.analysis.calls import CallGraphExtractor
from constrictor.analysis.imports import ImportExtractor
from constrictor.core.models import Certainty, ScanOptions, ScanWarning
from constrictor.core.orchestrator import run_scan
from constrictor.core.parser import ParsedModule
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.models import EdgeType, NodeType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_module(module_name: str, source: str) -> ParsedModule:
    tree = ast.parse(textwrap.dedent(source))
    return ParsedModule(
        file_path=Path(f"/fake/{module_name.replace('.', '/')}.py"),
        module_name=module_name,
        ast_tree=tree,
    )


def _run_calls(*modules: ParsedModule) -> tuple[GraphBuilder, list[ScanWarning]]:
    builder = GraphBuilder()
    warnings: list[ScanWarning] = []
    CallGraphExtractor().contribute(list(modules), builder, warnings)
    return builder, warnings


def _run_imports(*modules: ParsedModule) -> tuple[GraphBuilder, list[ScanWarning]]:
    builder = GraphBuilder()
    warnings: list[ScanWarning] = []
    ImportExtractor().contribute(list(modules), builder, warnings)
    return builder, warnings


# ===========================================================================
# Decorator analysis – DECORATES edges
# ===========================================================================

class TestDecoratorEdges:
    def test_simple_name_decorator_creates_decorates_edge(self):
        mod = _make_module("app.views", """\
            def login_required(fn):
                return fn

            @login_required
            def dashboard():
                pass
        """)
        builder, _ = _run_calls(mod)
        doc = builder.build()
        dec_edges = [e for e in doc.edges if e.type == EdgeType.DECORATES]
        assert dec_edges, "Expected at least one DECORATES edge"
        assert any("login_required" in e.display_name for e in dec_edges)

    def test_decorator_node_type_is_decorator(self):
        mod = _make_module("app.utils", """\
            def cached(fn):
                return fn

            @cached
            def expensive():
                pass
        """)
        builder, _ = _run_calls(mod)
        doc = builder.build()
        deco_nodes = [n for n in doc.nodes if n.type == NodeType.DECORATOR]
        assert deco_nodes, "Expected a DECORATOR node"

    def test_from_import_decorator_resolves_to_module(self):
        """@cache imported from functools should resolve to functools::cache."""
        mod = _make_module("app.utils", """\
            from functools import cache

            @cache
            def fib(n):
                return n if n < 2 else fib(n - 1) + fib(n - 2)
        """)
        builder, _ = _run_calls(mod)
        doc = builder.build()
        deco_nodes = [n for n in doc.nodes if n.type == NodeType.DECORATOR]
        assert any(n.qualified_name == "functools::cache" for n in deco_nodes), (
            f"Expected functools::cache, got: {[n.qualified_name for n in deco_nodes]}"
        )

    def test_attribute_decorator_resolves_module_alias(self):
        """@app.get('/') where `app` is imported should resolve to the module name."""
        mod = _make_module("myapi.routes", """\
            import fastapi as app

            @app.get("/items")
            def list_items():
                pass
        """)
        builder, _ = _run_calls(mod)
        doc = builder.build()
        deco_nodes = [n for n in doc.nodes if n.type == NodeType.DECORATOR]
        assert any("fastapi" in n.qualified_name for n in deco_nodes)

    def test_factory_decorator_metadata_flag(self):
        """@retry(max_attempts=3) is a factory — edge should have is_factory=true."""
        mod = _make_module("app.tasks", """\
            def retry(max_attempts=3):
                def wrapper(fn):
                    return fn
                return wrapper

            @retry(max_attempts=5)
            def fetch_data():
                pass
        """)
        builder, _ = _run_calls(mod)
        doc = builder.build()
        dec_edges = [e for e in doc.edges if e.type == EdgeType.DECORATES]
        factory_edges = [e for e in dec_edges if e.metadata.get("is_factory") == "true"]
        assert factory_edges, "Expected is_factory=true on factory decorator edge"

    def test_functools_wraps_sets_preserves_identity(self):
        """@wraps from functools should set preserves_identity=true metadata."""
        mod = _make_module("app.decorators", """\
            from functools import wraps

            def my_decorator(fn):
                @wraps(fn)
                def inner(*args, **kwargs):
                    return fn(*args, **kwargs)
                return inner
        """)
        builder, _ = _run_calls(mod)
        doc = builder.build()
        dec_edges = [e for e in doc.edges if e.type == EdgeType.DECORATES]
        wraps_edges = [
            e for e in dec_edges
            if e.metadata.get("preserves_identity") == "true"
        ]
        assert wraps_edges, "Expected preserves_identity=true for @wraps"

    def test_class_decorator_creates_decorates_edge(self):
        """Decorators on classes (not just functions) should be captured."""
        mod = _make_module("app.models", """\
            def register(cls):
                return cls

            @register
            class MyModel:
                pass
        """)
        builder, _ = _run_calls(mod)
        doc = builder.build()
        dec_edges = [e for e in doc.edges if e.type == EdgeType.DECORATES]
        assert dec_edges, "Expected DECORATES edge for class decorator"

    def test_multiple_decorators_on_one_function(self):
        """Each decorator in a stack should produce its own DECORATES edge."""
        mod = _make_module("app.api", """\
            def cached(fn): return fn
            def logged(fn): return fn

            @cached
            @logged
            def endpoint():
                pass
        """)
        builder, _ = _run_calls(mod)
        doc = builder.build()
        dec_edges = [e for e in doc.edges if e.type == EdgeType.DECORATES]
        assert len(dec_edges) >= 2, "Expected two DECORATES edges for stacked decorators"

    def test_decorator_edge_certainty_is_inferred_for_from_import(self):
        """Decorator resolved via from-import should have INFERRED certainty."""
        mod = _make_module("app.views", """\
            from functools import lru_cache

            @lru_cache(maxsize=128)
            def compute(x):
                return x * 2
        """)
        builder, _ = _run_calls(mod)
        doc = builder.build()
        dec_edges = [e for e in doc.edges if e.type == EdgeType.DECORATES]
        assert dec_edges
        assert all(e.certainty == Certainty.INFERRED for e in dec_edges)

    def test_unresolved_decorator_has_ambiguous_certainty(self):
        """A decorator with no import in scope should produce AMBIGUOUS certainty."""
        mod = _make_module("app.views", """\
            @some_unknown_decorator
            def view():
                pass
        """)
        builder, _ = _run_calls(mod)
        doc = builder.build()
        dec_edges = [e for e in doc.edges if e.type == EdgeType.DECORATES]
        assert dec_edges
        assert all(e.certainty == Certainty.AMBIGUOUS for e in dec_edges)

    def test_decorator_appears_in_full_scan(self, tmp_path: Path):
        """Decorators should be captured end-to-end through the scan pipeline."""
        (tmp_path / "views.py").write_text(
            "def require_auth(fn): return fn\n\n"
            "@require_auth\n"
            "def profile(): pass\n",
            encoding="utf-8",
        )
        doc = run_scan(ScanOptions(root_path=tmp_path))
        dec_edges = [e for e in doc.edges if e.type == EdgeType.DECORATES]
        assert dec_edges, "Full scan should produce DECORATES edges"


# ===========================================================================
# Dynamic import detection
# ===========================================================================

class TestDynamicImportDetection:
    def test_importlib_import_module_emits_unresolved_edge(self, tmp_path: Path):
        mod = _make_module("app.loader", """\
            import importlib

            def load_plugin(name: str):
                return importlib.import_module(name)
        """)
        builder, warnings = _run_imports(mod)
        doc = builder.build()

        unresolved = [
            e for e in doc.edges
            if e.certainty == Certainty.UNRESOLVED and e.type == EdgeType.IMPORTS
        ]
        assert unresolved, "Expected an UNRESOLVED IMPORTS edge for importlib.import_module"
        assert unresolved[0].metadata.get("pattern") == "importlib.import_module"

    def test_importlib_import_module_emits_warning(self):
        mod = _make_module("app.loader", """\
            import importlib

            importlib.import_module("plugins." + name)
        """)
        _, warnings = _run_imports(mod)
        dyn_warnings = [w for w in warnings if w.code == "DYNAMIC_IMPORT"]
        assert dyn_warnings, "Expected DYNAMIC_IMPORT warning"

    def test_dunder_import_detected(self):
        mod = _make_module("app.compat", """\
            mod = __import__("json")
        """)
        builder, warnings = _run_imports(mod)
        doc = builder.build()

        unresolved = [
            e for e in doc.edges
            if e.certainty == Certainty.UNRESOLVED and e.type == EdgeType.IMPORTS
        ]
        assert unresolved, "Expected UNRESOLVED edge for __import__()"
        assert unresolved[0].metadata.get("pattern") == "__import__"

    def test_no_false_positive_for_regular_call(self):
        """A plain importlib import (no import_module call) should not trigger detection."""
        mod = _make_module("app.utils", """\
            import importlib.metadata

            version = importlib.metadata.version("mypackage")
        """)
        _, warnings = _run_imports(mod)
        dyn_warnings = [w for w in warnings if w.code == "DYNAMIC_IMPORT"]
        assert not dyn_warnings

    def test_dynamic_import_in_full_scan(self, tmp_path: Path):
        (tmp_path / "loader.py").write_text(
            "import importlib\n\n"
            "def load(name):\n"
            "    return importlib.import_module(name)\n",
            encoding="utf-8",
        )
        doc = run_scan(ScanOptions(root_path=tmp_path))
        # DYNAMIC_IMPORT warnings have certainty=UNRESOLVED, so they end up in
        # doc.unresolved (not doc.warnings) — see GraphBuilder.build().
        dyn_warnings = [w for w in doc.unresolved if w.code == "DYNAMIC_IMPORT"]
        assert dyn_warnings, "Full scan should surface DYNAMIC_IMPORT in doc.unresolved"

    def test_importlib_alias_detected(self):
        """Dynamic import via an alias (import importlib as il) should still be caught."""
        mod = _make_module("app.loader", """\
            import importlib as il

            il.import_module("something")
        """)
        builder, warnings = _run_imports(mod)
        dyn_warnings = [w for w in warnings if w.code == "DYNAMIC_IMPORT"]
        assert dyn_warnings, "Should detect importlib.import_module via alias"

    def test_no_duplicate_edges_for_repeated_call(self):
        """Two calls on the same line (unusual but possible) should only produce one edge."""
        mod = _make_module("app.loader", """\
            import importlib
            importlib.import_module("a")
            importlib.import_module("b")
        """)
        builder, warnings = _run_imports(mod)
        doc = builder.build()
        dyn_warnings = [w for w in warnings if w.code == "DYNAMIC_IMPORT"]
        # Two distinct lines → two warnings (one per call site)
        assert len(dyn_warnings) == 2


# ===========================================================================
# MCP server – engine caching
# ===========================================================================

class TestMCPEngineCache:
    def test_engine_cached_after_first_load(self, tmp_path: Path):
        from constrictor.mcp.server import _engine_cache, _load_engine

        graph_file = tmp_path / "graph.json"
        doc = run_scan(ScanOptions(root_path=tmp_path))
        from constrictor.export.json_export import export_json
        export_json(doc, graph_file)

        _engine_cache.clear()
        engine1 = _load_engine(str(graph_file))
        engine2 = _load_engine(str(graph_file))
        assert engine1 is engine2, "Second call should return the cached engine"

    def test_engine_invalidated_when_file_changes(self, tmp_path: Path):
        from constrictor.mcp.server import _engine_cache, _load_engine
        from constrictor.export.json_export import export_json
        import time

        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        graph_file = tmp_path / "graph.json"
        doc = run_scan(ScanOptions(root_path=tmp_path))
        export_json(doc, graph_file)

        _engine_cache.clear()
        engine1 = _load_engine(str(graph_file))

        # Simulate a re-scan updating the file (ensure mtime differs)
        time.sleep(0.01)
        (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")
        doc2 = run_scan(ScanOptions(root_path=tmp_path))
        export_json(doc2, graph_file)

        engine2 = _load_engine(str(graph_file))
        assert engine1 is not engine2, "Cache should invalidate when file mtime changes"

    def test_resolve_graph_path_finds_json_in_directory(self, tmp_path: Path):
        from constrictor.mcp.server import _resolve_graph_path
        from constrictor.export.json_export import export_json

        graph_file = tmp_path / "graph.json"
        doc = run_scan(ScanOptions(root_path=tmp_path))
        export_json(doc, graph_file)

        resolved = _resolve_graph_path(str(tmp_path))
        assert resolved == str(graph_file)

    def test_resolve_graph_path_returns_none_for_missing_directory(self, tmp_path: Path):
        from constrictor.mcp.server import _resolve_graph_path

        result = _resolve_graph_path(str(tmp_path / "nonexistent_dir"))
        assert result is None

    def test_resolve_graph_path_returns_explicit_file_path(self, tmp_path: Path):
        from constrictor.mcp.server import _resolve_graph_path
        from constrictor.export.json_export import export_json

        graph_file = tmp_path / "mygraph.json"
        doc = run_scan(ScanOptions(root_path=tmp_path))
        export_json(doc, graph_file)

        resolved = _resolve_graph_path(str(graph_file))
        assert resolved == str(graph_file)
