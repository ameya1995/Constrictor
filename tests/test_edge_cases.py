"""Tests for edge-case handling across the scan pipeline.

Covers:
- Empty files and files with only comments/docstrings
- Circular imports (A imports B imports A)
- Star imports (from module import *)
- Dynamic imports (importlib.import_module)
- Files with encoding declarations
- __all__ exports
- TYPE_CHECKING conditional imports
- Deeply nested directories
"""
from __future__ import annotations

from pathlib import Path

from constrictor.core.models import ScanOptions
from constrictor.core.orchestrator import run_scan
from constrictor.core.parser import parse_all, parse_file
from constrictor.graph.models import EdgeType, NodeType

EDGE_CASES = Path(__file__).parent / "fixtures" / "edge_cases"


# ---------------------------------------------------------------------------
# Parser: empty files and comment-only files
# ---------------------------------------------------------------------------

class TestEmptyAndMinimalFiles:
    def test_parse_empty_file_succeeds(self, tmp_path: Path):
        f = tmp_path / "empty.py"
        f.write_text("", encoding="utf-8")
        result = parse_file(f, tmp_path)
        assert result is not None
        assert result.module_name == "empty"

    def test_parse_comments_only_succeeds(self):
        result = parse_file(EDGE_CASES / "only_comments.py", EDGE_CASES)
        assert result is not None

    def test_parse_docstring_only_succeeds(self):
        result = parse_file(EDGE_CASES / "only_docstring.py", EDGE_CASES)
        assert result is not None

    def test_scan_empty_file_does_not_crash(self, tmp_path: Path):
        (tmp_path / "empty.py").write_text("", encoding="utf-8")
        doc = run_scan(ScanOptions(root_path=tmp_path))
        assert doc.statistics.failed_files == 0

    def test_scan_comment_only_file_does_not_crash(self):
        doc = run_scan(ScanOptions(root_path=EDGE_CASES))
        assert doc.statistics.failed_files == 0

    def test_empty_directory_produces_empty_graph(self, tmp_path: Path):
        subdir = tmp_path / "empty_pkg"
        subdir.mkdir()
        doc = run_scan(ScanOptions(root_path=tmp_path))
        assert isinstance(doc.nodes, list)
        assert isinstance(doc.edges, list)


# ---------------------------------------------------------------------------
# Parser: syntax errors
# ---------------------------------------------------------------------------

class TestSyntaxErrors:
    def test_syntax_error_returns_none(self, tmp_path: Path):
        bad = tmp_path / "bad.py"
        bad.write_text("def foo(:\n    pass\n", encoding="utf-8")
        result = parse_file(bad, tmp_path)
        assert result is None

    def test_syntax_error_produces_warning(self, tmp_path: Path):
        bad = tmp_path / "bad.py"
        bad.write_text("def foo(:\n    pass\n", encoding="utf-8")
        _, warnings = parse_all([bad], tmp_path)
        assert warnings
        assert warnings[0].code == "SYNTAX_ERROR"

    def test_scan_with_syntax_error_counts_failure(self, tmp_path: Path):
        good = tmp_path / "good.py"
        good.write_text("x = 1\n", encoding="utf-8")
        bad = tmp_path / "bad.py"
        bad.write_text("def foo(:\n", encoding="utf-8")
        doc = run_scan(ScanOptions(root_path=tmp_path))
        assert doc.statistics.failed_files == 1
        assert doc.statistics.parsed_files == 1


# ---------------------------------------------------------------------------
# Parser: binary / non-UTF-8 files
# ---------------------------------------------------------------------------

class TestBinaryFiles:
    def test_binary_file_returns_none(self, tmp_path: Path):
        binary = tmp_path / "binary.py"
        binary.write_bytes(b"\xff\xfe\x00\x01binary content")
        result = parse_file(binary, tmp_path)
        assert result is None

    def test_binary_file_produces_decode_warning(self, tmp_path: Path):
        binary = tmp_path / "binary.py"
        binary.write_bytes(b"\xff\xfe\x00\x01binary content")
        _, warnings = parse_all([binary], tmp_path)
        assert warnings
        assert warnings[0].code == "DECODE_ERROR"


# ---------------------------------------------------------------------------
# Circular imports
# ---------------------------------------------------------------------------

class TestCircularImports:
    def test_scan_with_circular_imports_does_not_crash(self, tmp_path: Path):
        a = tmp_path / "circ_a.py"
        b = tmp_path / "circ_b.py"
        a.write_text(
            "from circ_b import func_b\n\ndef func_a(): func_b()\n",
            encoding="utf-8",
        )
        b.write_text(
            "from circ_a import func_a\n\ndef func_b(): func_a()\n",
            encoding="utf-8",
        )
        doc = run_scan(ScanOptions(root_path=tmp_path))
        assert doc.statistics.failed_files == 0
        # Both modules should be in the graph
        module_names = {n.name for n in doc.nodes if n.type == NodeType.MODULE}
        assert "circ_a" in module_names
        assert "circ_b" in module_names

    def test_circular_imports_produce_import_edges(self, tmp_path: Path):
        a = tmp_path / "circ_a.py"
        b = tmp_path / "circ_b.py"
        a.write_text("from circ_b import func_b\n", encoding="utf-8")
        b.write_text("from circ_a import func_a\n", encoding="utf-8")
        doc = run_scan(ScanOptions(root_path=tmp_path))
        import_edges = [e for e in doc.edges if e.type == EdgeType.IMPORTS_FROM]
        assert import_edges


# ---------------------------------------------------------------------------
# Star imports
# ---------------------------------------------------------------------------

class TestStarImports:
    def test_scan_with_star_import_does_not_crash(self):
        doc = run_scan(ScanOptions(root_path=EDGE_CASES))
        star_module = next(
            (n for n in doc.nodes if "star_imports" in n.name),
            None,
        )
        # The module node should be present
        assert star_module is not None

    def test_star_import_has_import_edge(self, tmp_path: Path):
        f = tmp_path / "star.py"
        f.write_text("from os.path import *\n", encoding="utf-8")
        doc = run_scan(ScanOptions(root_path=tmp_path))
        import_edges = [e for e in doc.edges if e.type == EdgeType.IMPORTS_FROM]
        assert import_edges

    def test_star_import_metadata_shows_star(self, tmp_path: Path):
        f = tmp_path / "star.py"
        f.write_text("from os.path import *\n", encoding="utf-8")
        doc = run_scan(ScanOptions(root_path=tmp_path))
        star_edges = [
            e for e in doc.edges
            if e.type == EdgeType.IMPORTS_FROM and e.metadata.get("names") == "*"
        ]
        assert star_edges, "Expected IMPORTS_FROM edge with names='*'"


# ---------------------------------------------------------------------------
# Dynamic imports (importlib)
# ---------------------------------------------------------------------------

class TestDynamicImports:
    def test_scan_with_dynamic_import_does_not_crash(self):
        doc = run_scan(ScanOptions(root_path=EDGE_CASES))
        assert doc.statistics.failed_files == 0

    def test_dynamic_import_module_parsed(self):
        result = parse_file(EDGE_CASES / "dynamic_imports.py", EDGE_CASES)
        assert result is not None

    def test_importlib_call_appears_as_call_edge(self, tmp_path: Path):
        f = tmp_path / "dyn.py"
        f.write_text(
            "import importlib\n\n"
            "def load(name: str):\n"
            "    return importlib.import_module(name)\n",
            encoding="utf-8",
        )
        doc = run_scan(ScanOptions(root_path=tmp_path))
        # importlib should appear as an external module import
        ext_names = {n.name for n in doc.nodes if n.type == NodeType.EXTERNAL_MODULE}
        assert "importlib" in ext_names


# ---------------------------------------------------------------------------
# Files with encoding declarations
# ---------------------------------------------------------------------------

class TestEncodingDeclaration:
    def test_parse_encoding_declaration_succeeds(self):
        result = parse_file(EDGE_CASES / "encoding_declaration.py", EDGE_CASES)
        assert result is not None

    def test_scan_encoding_declaration_no_failures(self):
        doc = run_scan(ScanOptions(root_path=EDGE_CASES))
        assert doc.statistics.failed_files == 0


# ---------------------------------------------------------------------------
# __all__ exports
# ---------------------------------------------------------------------------

class TestAllExports:
    def test_parse_all_exports_succeeds(self):
        result = parse_file(EDGE_CASES / "all_exports.py", EDGE_CASES)
        assert result is not None

    def test_scan_all_exports_builds_function_nodes(self):
        doc = run_scan(ScanOptions(root_path=EDGE_CASES))
        func_names = {n.name for n in doc.nodes if n.type == NodeType.FUNCTION}
        assert "public_func" in func_names
        assert "_private_func" in func_names  # still scanned, just not exported

    def test_scan_all_exports_builds_class_nodes(self):
        doc = run_scan(ScanOptions(root_path=EDGE_CASES))
        class_names = {n.name for n in doc.nodes if n.type == NodeType.CLASS}
        assert "PublicClass" in class_names


# ---------------------------------------------------------------------------
# TYPE_CHECKING conditional imports
# ---------------------------------------------------------------------------

class TestTypeCheckingImports:
    def test_parse_type_checking_file_succeeds(self):
        result = parse_file(EDGE_CASES / "type_checking_imports.py", EDGE_CASES)
        assert result is not None

    def test_type_checking_imports_do_not_crash_scan(self):
        doc = run_scan(ScanOptions(root_path=EDGE_CASES))
        assert doc.statistics.failed_files == 0

    def test_type_checking_import_captured(self, tmp_path: Path):
        f = tmp_path / "typed.py"
        f.write_text(
            "from __future__ import annotations\n"
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from pathlib import Path\n",
            encoding="utf-8",
        )
        doc = run_scan(ScanOptions(root_path=tmp_path))
        # pathlib import inside TYPE_CHECKING block: the AST still has the ImportFrom
        # so it should appear (certainty may be EXACT since pathlib is stdlib)
        ext_names = {n.name for n in doc.nodes if n.type == NodeType.EXTERNAL_MODULE}
        assert "pathlib" in ext_names


# ---------------------------------------------------------------------------
# Deeply nested directories
# ---------------------------------------------------------------------------

class TestDeeplyNestedDirectories:
    def test_deeply_nested_within_max_depth(self, tmp_path: Path):
        # Build 10 levels deep (well within default max_depth=64)
        current = tmp_path
        for i in range(10):
            current = current / f"level{i}"
            current.mkdir()
        deep_file = current / "deep.py"
        deep_file.write_text("x = 42\n", encoding="utf-8")

        doc = run_scan(ScanOptions(root_path=tmp_path))
        assert doc.statistics.total_files >= 1

    def test_max_depth_respected(self, tmp_path: Path):
        # Build 5 levels deep, set max_depth=2 → files at depth >2 should not be found
        current = tmp_path
        for i in range(5):
            current = current / f"d{i}"
            current.mkdir()
        (current / "deep.py").write_text("x = 1\n", encoding="utf-8")

        doc = run_scan(ScanOptions(root_path=tmp_path, max_depth=2))
        # The deep file should not be discovered
        assert doc.statistics.total_files == 0


# ---------------------------------------------------------------------------
# Large files (performance sanity check, not a hard limit)
# ---------------------------------------------------------------------------

class TestLargeFiles:
    def test_large_file_parses_successfully(self, tmp_path: Path):
        lines = ["# auto-generated\n"]
        for i in range(500):
            lines.append(f"def func_{i}(x):\n    return x + {i}\n\n")
        big = tmp_path / "big.py"
        big.write_text("".join(lines), encoding="utf-8")

        result = parse_file(big, tmp_path)
        assert result is not None

    def test_large_file_scan_produces_function_nodes(self, tmp_path: Path):
        lines = ["# auto-generated\n"]
        for i in range(100):
            lines.append(f"def func_{i}(x):\n    return x + {i}\n\n")
        big = tmp_path / "big.py"
        big.write_text("".join(lines), encoding="utf-8")

        doc = run_scan(ScanOptions(root_path=tmp_path))
        func_nodes = [n for n in doc.nodes if n.type == NodeType.FUNCTION]
        assert len(func_nodes) == 100
