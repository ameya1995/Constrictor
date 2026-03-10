from __future__ import annotations

import ast

from constrictor.core.models import Certainty, ScanWarning
from constrictor.core.parser import ParsedModule
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.id_factory import create_id
from constrictor.graph.models import EdgeType, NodeType

_ABC_NAMES = frozenset({"ABC", "ABCMeta"})
_PROTOCOL_NAMES = frozenset({"Protocol"})


def _cls_id(qualified_name: str) -> str:
    return create_id("func", qualified_name)


def _mod_id(module_name: str) -> str:
    return create_id("mod", module_name)


def _resolve_base(
    base: ast.expr,
    module_name: str,
    from_imports: dict[str, tuple[str, str]],
    import_aliases: dict[str, str],
    local_classes: dict[str, str],
) -> tuple[str, Certainty]:
    """Return (qualified_name, certainty) for a base class expression."""
    if isinstance(base, ast.Name):
        name = base.id
        if name in local_classes:
            return local_classes[name], Certainty.EXACT
        if name in from_imports:
            mod, orig = from_imports[name]
            return f"{mod}::{orig}" if mod else orig, Certainty.INFERRED
        # Builtins or unresolvable
        return f"<builtins>::{name}", Certainty.AMBIGUOUS

    elif isinstance(base, ast.Attribute):
        attr = base.attr
        if isinstance(base.value, ast.Name):
            obj = base.value.id
            if obj in import_aliases:
                mod = import_aliases[obj]
                return f"{mod}::{attr}", Certainty.INFERRED
        return f"<unknown>::{attr}", Certainty.AMBIGUOUS

    return "<complex_base>", Certainty.AMBIGUOUS


def _collect_scope_info(
    tree: ast.Module, module_name: str
) -> tuple[dict[str, str], dict[str, str], dict[str, tuple[str, str]]]:
    """Return (local_classes, import_aliases, from_imports)."""
    local_classes: dict[str, str] = {}
    import_aliases: dict[str, str] = {}
    from_imports: dict[str, tuple[str, str]] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            local_classes[node.name] = f"{module_name}::{node.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".")[0]
                import_aliases[local_name] = alias.name
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                local_name = alias.asname or alias.name
                from_imports[local_name] = (mod, alias.name)

    return local_classes, import_aliases, from_imports


class ClassHierarchyExtractor:
    name = "classes"

    def contribute(
        self,
        parsed_modules: list[ParsedModule],
        builder: GraphBuilder,
        warnings: list[ScanWarning],
    ) -> None:
        for module in parsed_modules:
            local_classes, import_aliases, from_imports = _collect_scope_info(
                module.ast_tree, module.module_name
            )
            mod_id = _mod_id(module.module_name)
            mod_fp = str(module.file_path)

            builder.add_node(
                id=mod_id,
                type=NodeType.MODULE,
                name=module.module_name,
                qualified_name=module.module_name,
                display_name=module.module_name,
                file_path=mod_fp,
                certainty=Certainty.EXACT,
            )

            self._process_classes(
                stmts=module.ast_tree.body,
                parent_id=mod_id,
                module=module,
                local_classes=local_classes,
                import_aliases=import_aliases,
                from_imports=from_imports,
                builder=builder,
                prefix=module.module_name,
            )

    def _process_classes(
        self,
        stmts: list[ast.stmt],
        parent_id: str,
        module: ParsedModule,
        local_classes: dict[str, str],
        import_aliases: dict[str, str],
        from_imports: dict[str, tuple[str, str]],
        builder: GraphBuilder,
        prefix: str,
    ) -> None:
        mod_fp = str(module.file_path)

        for stmt in stmts:
            if not isinstance(stmt, ast.ClassDef):
                continue

            cls_qname = f"{prefix}::{stmt.name}"
            cls_id = _cls_id(cls_qname)

            builder.add_node(
                id=cls_id,
                type=NodeType.CLASS,
                name=stmt.name,
                qualified_name=cls_qname,
                display_name=cls_qname,
                file_path=mod_fp,
                line_number=stmt.lineno,
                certainty=Certainty.EXACT,
            )
            builder.add_edge(
                source_id=parent_id,
                target_id=cls_id,
                type=EdgeType.CONTAINS,
                display_name=f"{parent_id} contains {cls_qname}",
                file_path=mod_fp,
                line_number=stmt.lineno,
                certainty=Certainty.EXACT,
            )

            # Process base classes
            for base in stmt.bases:
                base_qname, certainty = _resolve_base(
                    base, module.module_name, from_imports, import_aliases, local_classes
                )
                base_id = _cls_id(base_qname)

                builder.add_node(
                    id=base_id,
                    type=NodeType.CLASS,
                    name=base_qname.split("::")[-1],
                    qualified_name=base_qname,
                    display_name=base_qname,
                    certainty=certainty,
                )

                # Detect ABC/Protocol -> IMPLEMENTS edge instead of INHERITS
                base_short = base_qname.split("::")[-1]
                if base_short in _ABC_NAMES or base_short in _PROTOCOL_NAMES:
                    edge_type = EdgeType.IMPLEMENTS
                else:
                    edge_type = EdgeType.INHERITS

                builder.add_edge(
                    source_id=cls_id,
                    target_id=base_id,
                    type=edge_type,
                    display_name=f"{cls_qname} {'implements' if edge_type == EdgeType.IMPLEMENTS else 'inherits'} {base_qname}",
                    file_path=mod_fp,
                    line_number=stmt.lineno,
                    certainty=certainty,
                )

            # Extract methods with CONTAINS edges from class
            self._process_methods(stmt, cls_id, cls_qname, mod_fp, builder)

            # Recurse into nested classes
            self._process_classes(
                stmts=stmt.body,
                parent_id=cls_id,
                module=module,
                local_classes=local_classes,
                import_aliases=import_aliases,
                from_imports=from_imports,
                builder=builder,
                prefix=cls_qname,
            )

    def _process_methods(
        self,
        class_node: ast.ClassDef,
        cls_id: str,
        cls_qname: str,
        file_path: str,
        builder: GraphBuilder,
    ) -> None:
        for stmt in class_node.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_qname = f"{cls_qname}::{stmt.name}"
                method_id = _cls_id(method_qname)

                builder.add_node(
                    id=method_id,
                    type=NodeType.METHOD,
                    name=stmt.name,
                    qualified_name=method_qname,
                    display_name=method_qname,
                    file_path=file_path,
                    line_number=stmt.lineno,
                    certainty=Certainty.EXACT,
                )
                builder.add_edge(
                    source_id=cls_id,
                    target_id=method_id,
                    type=EdgeType.CONTAINS,
                    display_name=f"{cls_qname} contains {method_qname}",
                    file_path=file_path,
                    line_number=stmt.lineno,
                    certainty=Certainty.EXACT,
                )

    def post_process(self, builder: GraphBuilder) -> None:
        pass
