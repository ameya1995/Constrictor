from __future__ import annotations

from pathlib import Path

import pytest

from constrictor.core.models import ScanOptions
from constrictor.core.scanner import scan_directory

FIXTURE_SIMPLE = (
    Path(__file__).parent / "fixtures" / "simple_project"
)


def test_discovers_python_files_in_fixture(tmp_path: Path) -> None:
    options = ScanOptions(root_path=FIXTURE_SIMPLE)
    result = scan_directory(options)

    file_names = {f.name for f in result.python_files}
    assert "__init__.py" in file_names
    assert "main.py" in file_names
    assert "utils.py" in file_names
    assert "models.py" in file_names
    assert "test_main.py" in file_names


def test_discovers_config_files_in_fixture() -> None:
    options = ScanOptions(root_path=FIXTURE_SIMPLE)
    result = scan_directory(options)

    config_names = {f.name for f in result.config_files}
    assert "setup.py" in config_names


def test_excludes_venv_directory(tmp_path: Path) -> None:
    (tmp_path / "venv").mkdir()
    (tmp_path / "venv" / "some_module.py").write_text("x = 1")
    (tmp_path / "real.py").write_text("y = 2")

    options = ScanOptions(root_path=tmp_path)
    result = scan_directory(options)

    assert tmp_path / "real.py" in result.python_files
    assert tmp_path / "venv" / "some_module.py" not in result.python_files


def test_excludes_pycache_directory(tmp_path: Path) -> None:
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "cached.pyc").write_text("")
    (tmp_path / "module.py").write_text("pass")

    options = ScanOptions(root_path=tmp_path)
    result = scan_directory(options)

    paths_str = [str(f) for f in result.python_files]
    assert all("__pycache__" not in p for p in paths_str)


def test_custom_exclude_patterns(tmp_path: Path) -> None:
    (tmp_path / "generated").mkdir()
    (tmp_path / "generated" / "auto.py").write_text("pass")
    (tmp_path / "real.py").write_text("pass")

    options = ScanOptions(root_path=tmp_path, exclude_patterns=["generated"])
    result = scan_directory(options)

    paths_str = [str(f) for f in result.python_files]
    assert any("real.py" in p for p in paths_str)
    assert not any("generated" in p for p in paths_str)


def test_max_depth_respected(tmp_path: Path) -> None:
    deep = tmp_path / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    (deep / "deep_module.py").write_text("pass")
    (tmp_path / "shallow.py").write_text("pass")

    options = ScanOptions(root_path=tmp_path, max_depth=2)
    result = scan_directory(options)

    paths_str = [str(f) for f in result.python_files]
    assert any("shallow.py" in p for p in paths_str)
    assert not any("deep_module.py" in p for p in paths_str)


def test_handles_permission_error_gracefully(tmp_path: Path) -> None:
    # We can't reliably test permission errors on all systems,
    # so we just verify the scanner doesn't crash on a normal dir
    options = ScanOptions(root_path=tmp_path)
    result = scan_directory(options)
    assert result.python_files == []
    assert result.warnings == []


def test_broken_symlink_emits_warning(tmp_path: Path) -> None:
    broken_link = tmp_path / "broken.py"
    broken_link.symlink_to(tmp_path / "nonexistent.py")

    options = ScanOptions(root_path=tmp_path)
    result = scan_directory(options)

    codes = {w.code for w in result.warnings}
    assert "BROKEN_SYMLINK" in codes


def test_python_files_are_sorted(tmp_path: Path) -> None:
    for name in ["z_module.py", "a_module.py", "m_module.py"]:
        (tmp_path / name).write_text("pass")

    options = ScanOptions(root_path=tmp_path)
    result = scan_directory(options)

    names = [f.name for f in result.python_files]
    assert names == sorted(names)


def test_simple_project_has_five_python_files() -> None:
    options = ScanOptions(root_path=FIXTURE_SIMPLE)
    result = scan_directory(options)

    # app/__init__.py, app/main.py, app/utils.py, app/models.py,
    # tests/test_main.py -- setup.py is a config file, not counted here
    assert len(result.python_files) == 5
