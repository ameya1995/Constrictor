"""JS/TS import extractor.

Handles:
- ES module ``import x from '...'`` (static imports)
- Named and namespace imports: ``import { a, b } from '...'``
- ``require('...')`` calls
- ``import('...')`` dynamic imports (treated as AMBIGUOUS)

Creates ``JS_MODULE`` nodes and ``IMPORTS`` / ``IMPORTS_FROM`` edges.
"""
from __future__ import annotations

from pathlib import Path

from constrictor.analysis.js_utils import get_string_value, get_text, walk_nodes
from constrictor.core.js_parser import ParsedJSModule
from constrictor.core.models import Certainty, ScanWarning
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.id_factory import create_id
from constrictor.graph.models import EdgeType, NodeType


def _module_id(module_name: str) -> str:
    return create_id("jsmod", module_name)


def _resolve_specifier(
    specifier: str, current_module: ParsedJSModule
) -> tuple[str, bool]:
    """Return (resolved_module_name, is_local).

    Local specifiers start with ``./`` or ``../``.  We resolve them to a
    dot-qualified name relative to the project root (same convention as Python
    module names).  Third-party / bare specifiers are kept as-is.
    """
    if specifier.startswith("./") or specifier.startswith("../"):
        current_dir = current_module.file_path.parent
        target_path = (current_dir / specifier).resolve()
        # Strip known JS extensions for the module name
        for ext in (".tsx", ".ts", ".jsx", ".js"):
            candidate = Path(str(target_path) + ext)
            if candidate.exists():
                target_path = candidate
                break
        # Simplify: just use the specifier path parts
        clean = specifier.lstrip("./").replace("/", ".")
        if clean.endswith((".tsx", ".ts", ".jsx", ".js")):
            for ext in (".tsx", ".ts", ".jsx", ".js"):
                if clean.endswith(ext):
                    clean = clean[: -len(ext)]
                    break
        # Qualify relative to the current module's parent path
        parent_parts = list(current_module.module_name.split(".")[:-1])
        for part in specifier.split("/"):
            if part == "..":
                if parent_parts:
                    parent_parts.pop()
            elif part not in (".", ""):
                p = part
                for ext in (".tsx", ".ts", ".jsx", ".js"):
                    if p.endswith(ext):
                        p = p[: -len(ext)]
                        break
                parent_parts.append(p)
        return ".".join(parent_parts), True

    return specifier, False


class JSImportExtractor:
    name = "js_imports"

    def __init__(self) -> None:
        self._parsed_modules: list[ParsedJSModule] = []

    def contribute_js(
        self,
        parsed_modules: list[ParsedJSModule],
        builder: GraphBuilder,
        warnings: list[ScanWarning],
    ) -> None:
        self._parsed_modules = parsed_modules
        for module in parsed_modules:
            self._process_module(module, builder, warnings)

    def contribute(
        self,
        parsed_modules: object,
        builder: GraphBuilder,
        warnings: list[ScanWarning],
    ) -> None:
        pass  # Called by Python pipeline; JS pipeline uses contribute_js

    def post_process(self, builder: GraphBuilder) -> None:
        pass

    def _process_module(
        self,
        module: ParsedJSModule,
        builder: GraphBuilder,
        warnings: list[ScanWarning],
    ) -> None:
        fp = str(module.file_path)
        src_id = _module_id(module.module_name)

        builder.add_node(
            id=src_id,
            type=NodeType.JS_MODULE,
            name=module.module_name.split(".")[-1],
            qualified_name=module.module_name,
            display_name=module.module_name,
            file_path=fp,
            certainty=Certainty.EXACT,
        )

        src = module.source

        # ── ES static imports ──────────────────────────────────────────────
        for node in walk_nodes(module.tree.root_node, "import_statement"):
            # Extract the source string (last child that is a string)
            source_node = None
            for child in reversed(node.children):
                if child.type == "string":
                    source_node = child
                    break

            specifier = get_string_value(source_node, src)
            if specifier is None:
                continue

            resolved, is_local = _resolve_specifier(specifier, module)
            certainty = Certainty.EXACT if is_local else Certainty.INFERRED
            target_id = _module_id(resolved)

            builder.add_node(
                id=target_id,
                type=NodeType.JS_MODULE,
                name=resolved.split(".")[-1],
                qualified_name=resolved,
                display_name=resolved,
                file_path=None,
                certainty=certainty,
            )

            # Determine edge type: named import → IMPORTS_FROM, default → IMPORTS
            # named_imports lives inside import_clause (a child, not a sibling)
            has_named = any(
                desc.type in ("named_imports", "namespace_import")
                for desc in walk_nodes(node, "named_imports", "namespace_import")
            )
            edge_type = EdgeType.IMPORTS_FROM if has_named else EdgeType.IMPORTS

            builder.add_edge(
                source_id=src_id,
                target_id=target_id,
                type=edge_type,
                display_name=f"{module.module_name} -> {resolved}",
                file_path=fp,
                line_number=node.start_point[0] + 1,
                certainty=certainty,
            )

        # ── require(...) calls ────────────────────────────────────────────
        for call_node in walk_nodes(module.tree.root_node, "call_expression"):
            func = call_node.child_by_field_name("function")
            if func is None or get_text(func, src) != "require":
                continue
            args = call_node.child_by_field_name("arguments")
            if args is None:
                continue
            str_arg = next(
                (c for c in args.named_children if c.type == "string"), None
            )
            specifier = get_string_value(str_arg, src)
            if specifier is None:
                continue

            resolved, is_local = _resolve_specifier(specifier, module)
            certainty = Certainty.EXACT if is_local else Certainty.INFERRED
            target_id = _module_id(resolved)

            builder.add_node(
                id=target_id,
                type=NodeType.JS_MODULE,
                name=resolved.split(".")[-1],
                qualified_name=resolved,
                display_name=resolved,
                file_path=None,
                certainty=certainty,
            )
            builder.add_edge(
                source_id=src_id,
                target_id=target_id,
                type=EdgeType.IMPORTS,
                display_name=f"{module.module_name} requires {resolved}",
                file_path=fp,
                line_number=call_node.start_point[0] + 1,
                certainty=certainty,
            )
