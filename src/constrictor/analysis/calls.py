from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import dataclass, field

from constrictor.core.models import Certainty, ScanWarning
from constrictor.core.parser import ParsedModule
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.id_factory import create_id
from constrictor.graph.models import EdgeType, NodeType


def _func_id(qualified_name: str) -> str:
    return create_id("func", qualified_name)


def _mod_id(module_name: str) -> str:
    return create_id("mod", module_name)


def _decorator_id(qualified_name: str) -> str:
    return create_id("deco", qualified_name)


@dataclass
class _FuncInfo:
    qualified_name: str
    node_type: NodeType
    file_path: str
    line_number: int
    class_name: str | None = None


@dataclass
class _ModuleScope:
    """Tracks names defined/imported in a module for call resolution."""
    module_name: str
    # name -> qualified_name of local functions/classes
    local_defs: dict[str, str] = field(default_factory=dict)
    # alias -> module_name from import statements
    import_aliases: dict[str, str] = field(default_factory=dict)
    # name -> (module_name, original_name) from "from X import Y"
    from_imports: dict[str, tuple[str, str]] = field(default_factory=dict)


def _collect_scope(module: ParsedModule) -> _ModuleScope:
    scope = _ModuleScope(module_name=module.module_name)

    for node in ast.walk(module.ast_tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".")[0]
                scope.import_aliases[local_name] = alias.name

        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                local_name = alias.asname or alias.name
                scope.from_imports[local_name] = (mod, alias.name)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope.local_defs[node.name] = f"{module.module_name}::{node.name}"

        elif isinstance(node, ast.ClassDef):
            scope.local_defs[node.name] = f"{module.module_name}::{node.name}"

    return scope


def _collect_functions(module: ParsedModule) -> list[_FuncInfo]:
    """Walk top-level and class-level function/method definitions."""
    funcs: list[_FuncInfo] = []

    def _visit_body(
        stmts: list[ast.stmt],
        class_name: str | None,
        prefix: str,
    ) -> None:
        for stmt in stmts:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qname = f"{prefix}::{stmt.name}"
                ntype = NodeType.METHOD if class_name else NodeType.FUNCTION
                funcs.append(
                    _FuncInfo(
                        qualified_name=qname,
                        node_type=ntype,
                        file_path=str(module.file_path),
                        line_number=stmt.lineno,
                        class_name=class_name,
                    )
                )
                # Nested functions inside this function
                _visit_body(stmt.body, class_name=None, prefix=qname)

            elif isinstance(stmt, ast.ClassDef):
                cls_prefix = f"{prefix}::{stmt.name}"
                _visit_body(stmt.body, class_name=stmt.name, prefix=cls_prefix)

    _visit_body(module.ast_tree.body, class_name=None, prefix=module.module_name)
    return funcs


def _get_decorator_callable(decorator: ast.expr) -> ast.expr:
    """Strip factory wrapper: @retry(3) → the `retry` node itself."""
    if isinstance(decorator, ast.Call):
        return decorator.func
    return decorator


def _resolve_decorator_name(
    decorator: ast.expr,
    scope: _ModuleScope,
) -> tuple[str, str, Certainty]:
    """Return (qualified_name, display_name, certainty) for a decorator expression."""
    node = _get_decorator_callable(decorator)

    if isinstance(node, ast.Name):
        name = node.id
        # from functools import cache → functools::cache
        if name in scope.from_imports:
            mod, orig = scope.from_imports[name]
            if mod:
                return f"{mod}::{orig}", orig, Certainty.INFERRED
        # Local definition (e.g. a decorator defined in the same module)
        if name in scope.local_defs:
            return scope.local_defs[name], name, Certainty.EXACT
        return f"<unresolved>::{name}", name, Certainty.AMBIGUOUS

    elif isinstance(node, ast.Attribute):
        # Build dotted name: app.route → ["app", "route"]
        parts: list[str] = []
        cur: ast.expr = node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        parts.reverse()
        obj_name = parts[0]
        if obj_name in scope.import_aliases:
            mod = scope.import_aliases[obj_name]
            rest = "::".join(parts[1:])
            return f"{mod}::{rest}", parts[-1], Certainty.INFERRED
        attr_path = "::".join(parts)
        return attr_path, parts[-1], Certainty.AMBIGUOUS

    return "<dynamic>", "<dynamic>", Certainty.AMBIGUOUS


def _process_decorators(
    stmt: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    decorated_id: str,
    file_path: str,
    scope: _ModuleScope,
    builder: GraphBuilder,
) -> None:
    """Emit DECORATOR nodes and DECORATES edges for every decorator on *stmt*.

    This gives agents visibility into cross-cutting concerns (caching, auth,
    retry, logging, etc.) that rewrite call graphs without being captured by
    the framework-specific extractors.
    """
    for decorator in stmt.decorator_list:
        is_factory = isinstance(decorator, ast.Call)
        qname, display_name, certainty = _resolve_decorator_name(decorator, scope)

        deco_id = _decorator_id(qname)
        builder.add_node(
            id=deco_id,
            type=NodeType.DECORATOR,
            name=display_name,
            qualified_name=qname,
            display_name=qname,
            certainty=certainty,
        )

        meta: dict[str, str] = {}
        if is_factory:
            meta["is_factory"] = "true"
        # functools.wraps preserves the original function identity — flag it
        # so agents know the wrapper doesn't change the observable interface.
        if qname in ("functools::wraps", "<unresolved>::wraps"):
            meta["preserves_identity"] = "true"

        builder.add_edge(
            source_id=deco_id,
            target_id=decorated_id,
            type=EdgeType.DECORATES,
            display_name=f"{qname} decorates {decorated_id}",
            file_path=file_path,
            line_number=stmt.lineno,
            certainty=certainty,
            metadata=meta,
        )


def _resolve_call_target(
    call_node: ast.Call,
    scope: _ModuleScope,
    enclosing_class: str | None,
    all_modules: set[str],
) -> tuple[str | None, Certainty]:
    """Try to resolve a call node to a qualified name. Returns (qualified_name, certainty)."""
    func = call_node.func

    if isinstance(func, ast.Name):
        name = func.id
        # Local definition
        if name in scope.local_defs:
            return scope.local_defs[name], Certainty.EXACT
        # From-import
        if name in scope.from_imports:
            mod, orig = scope.from_imports[name]
            if mod:
                return f"{mod}::{orig}", Certainty.INFERRED
        # Could not resolve
        return f"<unresolved>::{name}", Certainty.AMBIGUOUS

    elif isinstance(func, ast.Attribute):
        attr = func.attr

        # self.method()
        if isinstance(func.value, ast.Name) and func.value.id == "self":
            if enclosing_class:
                return f"{scope.module_name}::{enclosing_class}::{attr}", Certainty.INFERRED
            return f"<self>::{attr}", Certainty.AMBIGUOUS

        # module.func() or obj.method()
        if isinstance(func.value, ast.Name):
            obj_name = func.value.id
            if obj_name in scope.import_aliases:
                mod = scope.import_aliases[obj_name]
                if mod in all_modules or any(m.startswith(mod + ".") for m in all_modules):
                    return f"{mod}::{attr}", Certainty.INFERRED
                return f"{mod}::{attr}", Certainty.AMBIGUOUS
            if obj_name in scope.from_imports:
                mod, orig = scope.from_imports[obj_name]
                return f"{mod}::{orig}::{attr}", Certainty.AMBIGUOUS

        return None, Certainty.AMBIGUOUS

    return None, Certainty.AMBIGUOUS


def _walk_calls_in_func(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    caller_id: str,
    caller_fp: str,
    scope: _ModuleScope,
    enclosing_class: str | None,
    all_modules: set[str],
    builder: GraphBuilder,
) -> None:
    for node in ast.walk(func_node):
        # Skip nested function/class definitions (they are their own callers)
        if node is not func_node and isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        if isinstance(node, ast.Call):
            target_qname, certainty = _resolve_call_target(
                node, scope, enclosing_class, all_modules
            )
            if target_qname is None:
                continue

            target_id = _func_id(target_qname)
            # Add stub target node only if it isn't already present
            builder.add_node(
                id=target_id,
                type=NodeType.FUNCTION,
                name=target_qname.split("::")[-1],
                qualified_name=target_qname,
                display_name=target_qname,
                certainty=certainty,
            )
            builder.add_edge(
                source_id=caller_id,
                target_id=target_id,
                type=EdgeType.CALLS,
                display_name=f"{caller_id} calls {target_qname}",
                file_path=caller_fp,
                line_number=node.lineno,
                certainty=certainty,
            )


class CallGraphExtractor:
    name = "calls"

    def contribute(
        self,
        parsed_modules: list[ParsedModule],
        builder: GraphBuilder,
        warnings: list[ScanWarning],
    ) -> None:
        all_modules: set[str] = {m.module_name for m in parsed_modules}

        for module in parsed_modules:
            scope = _collect_scope(module)
            mod_id = _mod_id(module.module_name)
            mod_fp = str(module.file_path)

            # Ensure the module node exists
            builder.add_node(
                id=mod_id,
                type=NodeType.MODULE,
                name=module.module_name,
                qualified_name=module.module_name,
                display_name=module.module_name,
                file_path=mod_fp,
                certainty=Certainty.EXACT,
            )

            self._process_body(
                stmts=module.ast_tree.body,
                parent_id=mod_id,
                module=module,
                scope=scope,
                enclosing_class=None,
                all_modules=all_modules,
                builder=builder,
                prefix=module.module_name,
            )

    def _process_body(
        self,
        stmts: Sequence[ast.stmt],
        parent_id: str,
        module: ParsedModule,
        scope: _ModuleScope,
        enclosing_class: str | None,
        all_modules: set[str],
        builder: GraphBuilder,
        prefix: str,
    ) -> None:
        mod_fp = str(module.file_path)

        for stmt in stmts:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qname = f"{prefix}::{stmt.name}"
                ntype = NodeType.METHOD if enclosing_class else NodeType.FUNCTION
                func_id = _func_id(qname)

                builder.add_node(
                    id=func_id,
                    type=ntype,
                    name=stmt.name,
                    qualified_name=qname,
                    display_name=qname,
                    file_path=mod_fp,
                    line_number=stmt.lineno,
                    certainty=Certainty.EXACT,
                )
                builder.add_edge(
                    source_id=parent_id,
                    target_id=func_id,
                    type=EdgeType.CONTAINS,
                    display_name=f"{parent_id} contains {qname}",
                    file_path=mod_fp,
                    line_number=stmt.lineno,
                    certainty=Certainty.EXACT,
                )

                _process_decorators(stmt, func_id, mod_fp, scope, builder)
                _walk_calls_in_func(
                    stmt, func_id, mod_fp, scope, enclosing_class, all_modules, builder
                )

                # Recurse into nested functions (not nested classes — handled below)
                nested_stmts = [
                    s for s in stmt.body
                    if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                self._process_body(
                    stmts=nested_stmts,
                    parent_id=func_id,
                    module=module,
                    scope=scope,
                    enclosing_class=enclosing_class,
                    all_modules=all_modules,
                    builder=builder,
                    prefix=qname,
                )

            elif isinstance(stmt, ast.ClassDef):
                cls_qname = f"{prefix}::{stmt.name}"
                cls_id = _func_id(cls_qname)

                # Class node is created by ClassHierarchyExtractor; add CONTAINS here
                # but don't overwrite — just ensure the edge exists.
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

                _process_decorators(stmt, cls_id, mod_fp, scope, builder)

                # Recurse into class body for methods
                self._process_body(
                    stmts=stmt.body,
                    parent_id=cls_id,
                    module=module,
                    scope=scope,
                    enclosing_class=stmt.name,
                    all_modules=all_modules,
                    builder=builder,
                    prefix=cls_qname,
                )

    def post_process(self, builder: GraphBuilder) -> None:
        pass
