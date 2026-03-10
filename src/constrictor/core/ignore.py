from __future__ import annotations

import fnmatch
from pathlib import Path

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


def load_ignore_patterns(
    root_path: Path,
    extra_exclude_files: list[Path] | None = None,
    extra_patterns: list[str] | None = None,
) -> list[str]:
    patterns: list[str] = list(_HARDCODED_DEFAULTS)

    ignore_file = root_path / _IGNORE_FILENAME
    if ignore_file.is_file():
        patterns.extend(_read_patterns_from_file(ignore_file))

    if extra_exclude_files:
        for ef in extra_exclude_files:
            patterns.extend(_read_patterns_from_file(ef))

    if extra_patterns:
        patterns.extend(extra_patterns)

    return patterns


def should_exclude(path: Path, patterns: list[str]) -> bool:
    name = path.name
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
        # Also match against the full path string for path-like patterns
        if "/" in pattern or "\\" in pattern:
            if fnmatch.fnmatch(str(path), pattern):
                return True
    return False
