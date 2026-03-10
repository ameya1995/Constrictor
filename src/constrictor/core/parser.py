from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from constrictor.core.models import Certainty, ScanWarning


@dataclass
class ParsedModule:
    file_path: Path
    module_name: str
    ast_tree: ast.Module


def _compute_module_name(file_path: Path, root_path: Path) -> str:
    """Convert a file path to a dot-qualified module name.

    Strips a leading 'src/' segment if present, so that
    src/constrictor/core/scanner.py -> constrictor.core.scanner.
    """
    try:
        rel = file_path.relative_to(root_path)
    except ValueError:
        rel = file_path

    parts = list(rel.parts)

    # Strip a leading 'src' directory (common layout convention)
    if parts and parts[0] == "src":
        parts = parts[1:]

    # Drop the .py extension from the last part
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]

    # Drop __init__ to get the package name instead
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]

    return ".".join(parts)


def parse_file(file_path: Path, root_path: Path) -> ParsedModule | None:
    try:
        source = file_path.read_bytes()
    except OSError:
        return None

    try:
        source_str = source.decode("utf-8")
    except UnicodeDecodeError:
        # Binary file masquerading as .py
        return None

    try:
        tree = ast.parse(source_str, filename=str(file_path))
    except SyntaxError:
        return None

    module_name = _compute_module_name(file_path, root_path)
    return ParsedModule(file_path=file_path, module_name=module_name, ast_tree=tree)


def parse_all(
    files: list[Path], root_path: Path
) -> tuple[list[ParsedModule], list[ScanWarning]]:
    modules: list[ParsedModule] = []
    warnings: list[ScanWarning] = []

    for file_path in files:
        result = parse_file(file_path, root_path)
        if result is None:
            # Determine the reason by re-attempting
            try:
                raw = file_path.read_bytes()
                try:
                    src = raw.decode("utf-8")
                    try:
                        ast.parse(src, filename=str(file_path))
                        # If we get here, something else went wrong on first attempt
                        code = "PARSE_ERROR"
                        msg = f"Failed to parse {file_path}"
                    except SyntaxError as exc:
                        code = "SYNTAX_ERROR"
                        msg = f"Syntax error in {file_path}: {exc}"
                except UnicodeDecodeError:
                    code = "DECODE_ERROR"
                    msg = f"Cannot decode {file_path} as UTF-8 (binary file?)"
            except OSError as exc:
                code = "IO_ERROR"
                msg = f"Cannot read {file_path}: {exc}"

            warnings.append(
                ScanWarning(
                    code=code,
                    message=msg,
                    path=str(file_path),
                    certainty=Certainty.UNRESOLVED,
                )
            )
        else:
            modules.append(result)

    return modules, warnings
