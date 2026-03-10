from __future__ import annotations

import ast
import sys
from pathlib import Path

from constrictor.core.models import Certainty, ScanWarning
from constrictor.core.parser import ParsedModule
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.id_factory import create_id
from constrictor.graph.models import EdgeType, NodeType

_STDLIB_NAMES: frozenset[str] = frozenset(sys.stdlib_module_names)  # type: ignore[attr-defined]


def _module_id(qualified_name: str, node_type: NodeType) -> str:
    prefix = "mod" if node_type == NodeType.MODULE else "extmod"
    return create_id(prefix, qualified_name)


def _resolve_relative_import(
    module: str | None,
    level: int,
    importing_module_name: str,
) -> str | None:
    """Resolve a relative import to an absolute module name.

    E.g. in package `app.routes`, `from .models import User` (level=1, module="models")
    -> "app.models"
    """
    parts = importing_module_name.split(".")
    # Go up `level` levels from the current package
    # level=1 means same package (drop last segment), level=2 means parent, etc.
    base_parts = parts[: max(0, len(parts) - level)]
    if module:
        base_parts = base_parts + module.split(".")
    return ".".join(base_parts) if base_parts else None


def _classify_module(
    module_name: str, root_path: Path, file_lookup: dict[str, Path]
) -> tuple[NodeType, Certainty]:
    """Return the NodeType and Certainty for a given module name."""
    top_level = module_name.split(".")[0]

    if top_level in _STDLIB_NAMES:
        return NodeType.EXTERNAL_MODULE, Certainty.EXACT

    if module_name in file_lookup or top_level in file_lookup:
        return NodeType.MODULE, Certainty.EXACT

    # Could not place it — treat as external (third-party or unresolvable)
    return NodeType.EXTERNAL_MODULE, Certainty.INFERRED


def _build_file_lookup(parsed_modules: list[ParsedModule]) -> dict[str, Path]:
    """Build a mapping from module name to file path for quick local resolution."""
    return {m.module_name: m.file_path for m in parsed_modules}


class ImportExtractor:
    name = "imports"

    def contribute(
        self,
        parsed_modules: list[ParsedModule],
        builder: GraphBuilder,
        warnings: list[ScanWarning],
    ) -> None:
        file_lookup = _build_file_lookup(parsed_modules)

        for module in parsed_modules:
            source_id = _module_id(module.module_name, NodeType.MODULE)
            source_fp = str(module.file_path)

            builder.add_node(
                id=source_id,
                type=NodeType.MODULE,
                name=module.module_name,
                qualified_name=module.module_name,
                display_name=module.module_name,
                file_path=source_fp,
                certainty=Certainty.EXACT,
            )

            for node in ast.walk(module.ast_tree):
                if isinstance(node, ast.Import):
                    self._handle_import(
                        node, source_id, source_fp, node.lineno,
                        file_lookup, builder, warnings,
                    )
                elif isinstance(node, ast.ImportFrom):
                    self._handle_import_from(
                        node, module.module_name, source_id, source_fp,
                        file_lookup, builder, warnings,
                    )

    def _handle_import(
        self,
        node: ast.Import,
        source_id: str,
        source_fp: str,
        line: int,
        file_lookup: dict[str, Path],
        builder: GraphBuilder,
        warnings: list[ScanWarning],
    ) -> None:
        for alias in node.names:
            target_name = alias.name
            node_type, certainty = _classify_module(
                target_name, Path(source_fp).parent, file_lookup
            )
            target_id = _module_id(target_name, node_type)

            builder.add_node(
                id=target_id,
                type=node_type,
                name=target_name,
                qualified_name=target_name,
                display_name=target_name,
                certainty=certainty,
            )
            builder.add_edge(
                source_id=source_id,
                target_id=target_id,
                type=EdgeType.IMPORTS,
                display_name=f"{source_id} imports {target_name}",
                file_path=source_fp,
                line_number=line,
                certainty=certainty,
            )

    def _handle_import_from(
        self,
        node: ast.ImportFrom,
        importing_module_name: str,
        source_id: str,
        source_fp: str,
        file_lookup: dict[str, Path],
        builder: GraphBuilder,
        warnings: list[ScanWarning],
    ) -> None:
        level = node.level or 0
        raw_module = node.module

        if level > 0:
            # Relative import
            resolved = _resolve_relative_import(raw_module, level, importing_module_name)
            if resolved is None:
                warnings.append(
                    ScanWarning(
                        code="UNRESOLVABLE_RELATIVE_IMPORT",
                        message=(
                            f"Could not resolve relative import "
                            f"'{'.' * level}{raw_module or ''}' in {source_fp}"
                        ),
                        path=source_fp,
                        certainty=Certainty.UNRESOLVED,
                    )
                )
                return
            target_name = resolved
            node_type = NodeType.MODULE
            certainty = Certainty.EXACT if target_name in file_lookup else Certainty.INFERRED
        else:
            if raw_module is None:
                return
            target_name = raw_module
            node_type, certainty = _classify_module(
                target_name, Path(source_fp).parent, file_lookup
            )

        target_id = _module_id(target_name, node_type)

        builder.add_node(
            id=target_id,
            type=node_type,
            name=target_name,
            qualified_name=target_name,
            display_name=target_name,
            certainty=certainty,
        )
        builder.add_edge(
            source_id=source_id,
            target_id=target_id,
            type=EdgeType.IMPORTS_FROM,
            display_name=f"{source_id} imports from {target_name}",
            file_path=source_fp,
            line_number=node.lineno,
            certainty=certainty,
            metadata={"names": ", ".join(a.name for a in node.names)},
        )

    def post_process(self, builder: GraphBuilder) -> None:
        pass
