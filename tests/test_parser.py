from __future__ import annotations

import ast
from pathlib import Path

import pytest

from constrictor.core.parser import ParsedModule, parse_all, parse_file

FIXTURE_SIMPLE = Path(__file__).parent / "fixtures" / "simple_project"


def test_parse_valid_file(tmp_path: Path) -> None:
    py_file = tmp_path / "module.py"
    py_file.write_text("x = 1\ny = x + 2\n")

    result = parse_file(py_file, tmp_path)

    assert result is not None
    assert isinstance(result, ParsedModule)
    assert result.file_path == py_file
    assert result.module_name == "module"
    assert isinstance(result.ast_tree, ast.Module)


def test_parse_syntax_error_returns_none(tmp_path: Path) -> None:
    bad_file = tmp_path / "broken.py"
    bad_file.write_text("def foo(:\n    pass\n")  # syntax error

    result = parse_file(bad_file, tmp_path)
    assert result is None


def test_parse_binary_file_returns_none(tmp_path: Path) -> None:
    binary_file = tmp_path / "binary.py"
    binary_file.write_bytes(b"\xff\xfe\x00\x01invalid bytes")

    result = parse_file(binary_file, tmp_path)
    assert result is None


def test_module_name_nested(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    module_file = tmp_path / "pkg" / "submodule.py"
    module_file.write_text("pass")

    result = parse_file(module_file, tmp_path)
    assert result is not None
    assert result.module_name == "pkg.submodule"


def test_module_name_strips_src_prefix(tmp_path: Path) -> None:
    src = tmp_path / "src" / "mypkg" / "core"
    src.mkdir(parents=True)
    module_file = src / "utils.py"
    module_file.write_text("pass")

    result = parse_file(module_file, tmp_path)
    assert result is not None
    assert result.module_name == "mypkg.core.utils"


def test_module_name_init_becomes_package(tmp_path: Path) -> None:
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    init_file = pkg / "__init__.py"
    init_file.write_text("")

    result = parse_file(init_file, tmp_path)
    assert result is not None
    assert result.module_name == "mypkg"


def test_parse_all_returns_modules_and_warnings(tmp_path: Path) -> None:
    good = tmp_path / "good.py"
    good.write_text("x = 1")
    bad = tmp_path / "bad.py"
    bad.write_text("def foo(:\n    pass")

    modules, warnings = parse_all([good, bad], tmp_path)

    assert len(modules) == 1
    assert modules[0].module_name == "good"
    assert len(warnings) == 1
    assert warnings[0].code == "SYNTAX_ERROR"
    assert "bad.py" in warnings[0].path


def test_parse_all_empty_list(tmp_path: Path) -> None:
    modules, warnings = parse_all([], tmp_path)
    assert modules == []
    assert warnings == []


def test_parse_all_fixture_project() -> None:
    py_files = sorted(FIXTURE_SIMPLE.rglob("*.py"))
    modules, warnings = parse_all(py_files, FIXTURE_SIMPLE)

    # All 5 fixture files (+ setup.py) should parse cleanly
    assert len(warnings) == 0
    assert len(modules) == len(py_files)


def test_parse_file_with_encoding_declaration(tmp_path: Path) -> None:
    py_file = tmp_path / "encoded.py"
    py_file.write_text("# -*- coding: utf-8 -*-\nx = 'héllo'\n", encoding="utf-8")

    result = parse_file(py_file, tmp_path)
    assert result is not None
    assert result.module_name == "encoded"


def test_parse_all_binary_file_emits_decode_warning(tmp_path: Path) -> None:
    binary_file = tmp_path / "junk.py"
    binary_file.write_bytes(b"\xff\xfe binary garbage")

    modules, warnings = parse_all([binary_file], tmp_path)
    assert len(modules) == 0
    assert len(warnings) == 1
    assert warnings[0].code == "DECODE_ERROR"
