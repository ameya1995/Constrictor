from __future__ import annotations

import ast

from constrictor.core.models import Certainty, ScanWarning
from constrictor.core.parser import ParsedModule
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.id_factory import create_id
from constrictor.graph.models import EdgeType, NodeType

_WRAPPER_TYPES = frozenset({
    "Optional", "Union", "List", "list", "Set", "set",
    "Dict", "dict", "Tuple", "tuple", "Sequence",
    "Iterable", "Iterator", "Generator", "Awaitable",
    "Annotated", "ClassVar", "Final", "Mapped",
})


def _func_id(qualified_name: str) -> str:
    return create_id("func", qualified_name)


def _unwrap_annotation(node: ast.expr) -> list[str]:
    """Recursively extract type names from an annotation, unwrapping containers."""
    names: list[str] = []
    if isinstance(node, ast.Name):
        if node.id not in _WRAPPER_TYPES:
            names.append(node.id)
    elif isinstance(node, ast.Attribute):
        names.append(node.attr)
    elif isinstance(node, ast.Subscript):
        # e.g. Optional[X], List[X], Union[X, Y], Mapped[X]
        outer = node.value
        inner = node.slice

        # Skip the outer wrapper itself; only recurse into the slice
        if not (isinstance(outer, ast.Name) and outer.id in _WRAPPER_TYPES):
            names.extend(_unwrap_annotation(outer))

        names.extend(_unwrap_annotation(inner))
    elif isinstance(node, ast.Tuple):
        # Union contents, e.g. Union[A, B]
        for elt in node.elts:
            names.extend(_unwrap_annotation(elt))
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        # PEP 604: X | Y
        names.extend(_unwrap_annotation(node.left))
        names.extend(_unwrap_annotation(node.right))
    elif isinstance(node, ast.Constant) and isinstance(node.value, str):
        # Forward reference as string literal: "MyModel"
        names.append(node.value)
    return names


def _build_class_lookup(parsed_modules: list[ParsedModule]) -> dict[str, str]:
    """Map simple class name -> qualified name across all parsed modules."""
    lookup: dict[str, str] = {}
    for module in parsed_modules:
        for node in ast.walk(module.ast_tree):
            if isinstance(node, ast.ClassDef):
                qname = f"{module.module_name}::{node.name}"
                lookup[node.name] = qname
    return lookup


class TypeAnnotationExtractor:
    name = "type_annotations"

    def contribute(
        self,
        parsed_modules: list[ParsedModule],
        builder: GraphBuilder,
        warnings: list[ScanWarning],
    ) -> None:
        class_lookup = _build_class_lookup(parsed_modules)

        for module in parsed_modules:
            self._process_module(module, builder, warnings, class_lookup)

    def _process_module(
        self,
        module: ParsedModule,
        builder: GraphBuilder,
        warnings: list[ScanWarning],
        class_lookup: dict[str, str],
    ) -> None:
        fp = str(module.file_path)
        self._visit_body(
            stmts=module.ast_tree.body,
            module=module,
            builder=builder,
            class_lookup=class_lookup,
            fp=fp,
            prefix=module.module_name,
            enclosing_func_qname=None,
        )

    def _visit_body(
        self,
        stmts: list[ast.stmt],
        module: ParsedModule,
        builder: GraphBuilder,
        class_lookup: dict[str, str],
        fp: str,
        prefix: str,
        enclosing_func_qname: str | None,
    ) -> None:
        for stmt in stmts:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_qname = f"{prefix}::{stmt.name}"
                func_id = _func_id(func_qname)
                # Ensure the function node exists (may be a stub)
                builder.add_node(
                    id=func_id,
                    type=NodeType.FUNCTION,
                    name=stmt.name,
                    qualified_name=func_qname,
                    display_name=func_qname,
                    file_path=fp,
                    line_number=stmt.lineno,
                    certainty=Certainty.EXACT,
                )

                # Parameter annotations
                all_args = stmt.args.args + stmt.args.kwonlyargs
                if stmt.args.vararg:
                    all_args.append(stmt.args.vararg)
                if stmt.args.kwarg:
                    all_args.append(stmt.args.kwarg)

                for arg in all_args:
                    if arg.arg == "self":
                        continue
                    self._emit_type_edges(
                        annotation=arg.annotation,
                        source_id=func_id,
                        source_qname=func_qname,
                        context=f"param {arg.arg}",
                        class_lookup=class_lookup,
                        builder=builder,
                        fp=fp,
                        line=stmt.lineno,
                    )

                # Return annotation
                self._emit_type_edges(
                    annotation=stmt.returns,
                    source_id=func_id,
                    source_qname=func_qname,
                    context="return",
                    class_lookup=class_lookup,
                    builder=builder,
                    fp=fp,
                    line=stmt.lineno,
                )

                # Recurse into function body
                self._visit_body(
                    stmts=stmt.body,
                    module=module,
                    builder=builder,
                    class_lookup=class_lookup,
                    fp=fp,
                    prefix=func_qname,
                    enclosing_func_qname=func_qname,
                )

            elif isinstance(stmt, ast.ClassDef):
                cls_qname = f"{prefix}::{stmt.name}"
                self._visit_body(
                    stmts=stmt.body,
                    module=module,
                    builder=builder,
                    class_lookup=class_lookup,
                    fp=fp,
                    prefix=cls_qname,
                    enclosing_func_qname=None,
                )

            elif isinstance(stmt, ast.AnnAssign):
                # Module-level or class-level annotated assignments
                if enclosing_func_qname:
                    source_id = _func_id(enclosing_func_qname)
                    source_qname = enclosing_func_qname
                else:
                    # Use the module node
                    source_id = create_id("mod", module.module_name)
                    source_qname = module.module_name

                self._emit_type_edges(
                    annotation=stmt.annotation,
                    source_id=source_id,
                    source_qname=source_qname,
                    context="annotated assignment",
                    class_lookup=class_lookup,
                    builder=builder,
                    fp=fp,
                    line=stmt.lineno,
                )

    def _emit_type_edges(
        self,
        annotation: ast.expr | None,
        source_id: str,
        source_qname: str,
        context: str,
        class_lookup: dict[str, str],
        builder: GraphBuilder,
        fp: str,
        line: int,
    ) -> None:
        if annotation is None:
            return
        type_names = _unwrap_annotation(annotation)
        seen: set[str] = set()
        for type_name in type_names:
            if type_name in seen or type_name not in class_lookup:
                continue
            seen.add(type_name)
            cls_qname = class_lookup[type_name]
            cls_id = _func_id(cls_qname)
            builder.add_edge(
                source_id=source_id,
                target_id=cls_id,
                type=EdgeType.TYPE_ANNOTATED,
                display_name=f"{source_qname} [{context}] -> {type_name}",
                file_path=fp,
                line_number=line,
                certainty=Certainty.EXACT,
            )

    def post_process(self, builder: GraphBuilder) -> None:
        pass
