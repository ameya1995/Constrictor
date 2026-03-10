"""JS/TS parser backed by tree-sitter.

Produces ``ParsedJSModule`` instances that the JS analysis extractors consume.
Falls back gracefully when tree-sitter grammars are not installed by returning
``None`` and emitting a ``ScanWarning``.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from constrictor.core.models import Certainty, ScanWarning

# ---------------------------------------------------------------------------
# Lazy grammar loading – avoids hard-importing tree-sitter at module level so
# the package remains importable even when the optional extras are absent.
# ---------------------------------------------------------------------------

_JS_LANG: object | None = None
_TS_LANG: object | None = None
_TSX_LANG: object | None = None
_TREE_SITTER_AVAILABLE: bool | None = None


def _ensure_languages() -> bool:
    """Load tree-sitter language objects once; return True if available."""
    global _JS_LANG, _TS_LANG, _TSX_LANG, _TREE_SITTER_AVAILABLE
    if _TREE_SITTER_AVAILABLE is not None:
        return _TREE_SITTER_AVAILABLE

    try:
        import tree_sitter_javascript as _tsj  # type: ignore[import]
        import tree_sitter_typescript as _tst  # type: ignore[import]
        from tree_sitter import Language  # type: ignore[import]

        _JS_LANG = Language(_tsj.language())
        _TS_LANG = Language(_tst.language_typescript())
        _TSX_LANG = Language(_tst.language_tsx())
        _TREE_SITTER_AVAILABLE = True
    except Exception:
        _TREE_SITTER_AVAILABLE = False

    return _TREE_SITTER_AVAILABLE  # type: ignore[return-value]


def _get_language(path: Path) -> object | None:
    if not _ensure_languages():
        return None
    suffix = path.suffix.lower()
    if suffix in (".tsx",):
        return _TSX_LANG
    if suffix in (".ts",):
        return _TS_LANG
    return _JS_LANG


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ParsedJSModule:
    file_path: Path
    module_name: str
    source: bytes
    tree: object  # tree_sitter.Tree
    is_jsx: bool = False
    is_typescript: bool = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_js_file(file_path: Path, root_path: Path) -> ParsedJSModule | None:
    """Parse a single JS/TS file.  Returns None on hard errors.

    Callers should add a ScanWarning when None is returned.
    """
    lang = _get_language(file_path)
    if lang is None:
        return None

    try:
        source = file_path.read_bytes()
    except (OSError, PermissionError):
        return None

    try:
        from tree_sitter import Parser  # type: ignore[import]

        parser = Parser(lang)
        tree = parser.parse(source)
    except Exception:
        return None

    module_name = _derive_module_name(file_path, root_path)
    suffix = file_path.suffix.lower()

    return ParsedJSModule(
        file_path=file_path,
        module_name=module_name,
        source=source,
        tree=tree,
        is_jsx=suffix in (".jsx", ".tsx"),
        is_typescript=suffix in (".ts", ".tsx"),
    )


def parse_all_js(
    files: list[Path],
    root_path: Path,
) -> tuple[list[ParsedJSModule], list[ScanWarning]]:
    """Parse every JS/TS file; collect warnings for failures."""
    if not _ensure_languages():
        warnings: list[ScanWarning] = [
            ScanWarning(
                code="JS_PARSER_UNAVAILABLE",
                message=(
                    "tree-sitter JS/TS grammars are not installed. "
                    "Install them with: pip install tree-sitter "
                    "tree-sitter-javascript tree-sitter-typescript"
                ),
                certainty=Certainty.UNRESOLVED,
            )
        ]
        return [], warnings

    parsed: list[ParsedJSModule] = []
    warnings = []

    for fp in files:
        module = parse_js_file(fp, root_path)
        if module is None:
            warnings.append(
                ScanWarning(
                    code="JS_PARSE_ERROR",
                    message=f"Failed to parse JS/TS file: {fp}",
                    path=str(fp),
                    certainty=Certainty.UNRESOLVED,
                )
            )
        else:
            parsed.append(module)

    return parsed, warnings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _derive_module_name(file_path: Path, root_path: Path) -> str:
    """Convert a file path to a dot-qualified module name, stripping the extension.

    Example: ``frontend/src/components/UserList.tsx``
    → ``frontend.src.components.UserList``
    """
    try:
        rel = file_path.relative_to(root_path)
    except ValueError:
        rel = file_path

    parts = list(rel.parts)
    if parts:
        # Strip extension from the last part
        last = parts[-1]
        for ext in (".tsx", ".ts", ".jsx", ".js"):
            if last.endswith(ext):
                parts[-1] = last[: -len(ext)]
                break

    return ".".join(parts)
