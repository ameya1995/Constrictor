from __future__ import annotations

import fnmatch
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]

_HARDCODED_DEFAULTS: list[str] = [
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "env",
    ".env",
    "node_modules",
    ".tox",
    ".nox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "*.egg-info",
    "dist",
    "build",
]

_IGNORE_FILENAME = ".constrictor_ignore"
_PYPROJECT_FILENAME = "pyproject.toml"


def _read_patterns_from_file(path: Path) -> list[str]:
    patterns: list[str] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                patterns.append(stripped)
    except OSError:
        pass
    return patterns


def _read_pyproject_patterns(root_path: Path) -> list[str]:
    """Read exclude patterns from [tool.constrictor] in pyproject.toml."""
    if tomllib is None:
        return []
    pyproject = root_path / _PYPROJECT_FILENAME
    if not pyproject.is_file():
        return []
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except Exception:
        return []
    exclude = data.get("tool", {}).get("constrictor", {}).get("exclude", [])
    if not isinstance(exclude, list):
        return []
    return [str(p) for p in exclude if isinstance(p, str)]


def load_ignore_patterns(
    root_path: Path,
    extra_exclude_files: list[Path] | None = None,
    extra_patterns: list[str] | None = None,
) -> list[str]:
    # Priority (later entries win on conflict):
    # hardcoded defaults -> pyproject.toml -> .constrictor_ignore -> --exclude-file -> --exclude
    patterns: list[str] = list(_HARDCODED_DEFAULTS)

    patterns.extend(_read_pyproject_patterns(root_path))

    ignore_file = root_path / _IGNORE_FILENAME
    if ignore_file.is_file():
        patterns.extend(_read_patterns_from_file(ignore_file))

    if extra_exclude_files:
        for ef in extra_exclude_files:
            patterns.extend(_read_patterns_from_file(ef))

    if extra_patterns:
        patterns.extend(extra_patterns)

    return patterns


def should_exclude(path: Path, patterns: list[str], root: Path | None = None) -> bool:
    name = path.name

    # Compute the relative path string (forward slashes) for directory-style matching.
    rel_str: str | None = None
    if root is not None:
        try:
            rel_str = path.relative_to(root).as_posix()
        except ValueError:
            rel_str = None

    for pattern in patterns:
        has_sep = "/" in pattern or "\\" in pattern

        if has_sep:
            # Match against relative path when available, otherwise absolute path.
            target = rel_str if rel_str is not None else str(path)
            if fnmatch.fnmatch(target, pattern):
                return True
            # Also support trailing-slash directory patterns like "migrations/"
            norm = pattern.rstrip("/\\")
            if "/" not in norm and "\\" not in norm:
                if fnmatch.fnmatch(name, norm):
                    return True
            elif rel_str is not None and fnmatch.fnmatch(rel_str, norm):
                return True
        else:
            # Simple basename pattern — fast path.
            if fnmatch.fnmatch(name, pattern):
                return True

    return False
