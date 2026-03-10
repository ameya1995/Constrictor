from __future__ import annotations

import ast

from constrictor.core.models import Certainty, ScanWarning
from constrictor.core.parser import ParsedModule
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.id_factory import create_id
from constrictor.graph.models import EdgeType, NodeType

_HTTP_METHODS = frozenset(
    {"get", "post", "put", "delete", "patch", "options", "head", "trace"}
)


def _endpoint_id(method: str, path: str) -> str:
    return create_id("endpoint", method.upper(), path)


def _func_id(qualified_name: str) -> str:
    return create_id("func", qualified_name)


def _get_string_value(node: ast.expr | None) -> str | None:
    """Extract a plain string value from a constant or joined-string node."""
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _extract_decorator_route(
    decorator: ast.expr,
) -> tuple[str, str] | None:
    """Return (http_method, path) if the decorator is a FastAPI/APIRouter route decorator.

    Handles patterns: @app.get("/path"), @router.post("/path"), @app_v2.delete(...)
    """
    if not isinstance(decorator, ast.Call):
        return None
    func = decorator.func
    if not isinstance(func, ast.Attribute):
        return None
    method = func.attr.lower()
    if method not in _HTTP_METHODS:
        return None

    # Extract path from first positional argument
    if decorator.args:
        path = _get_string_value(decorator.args[0]) or "<dynamic>"
    elif decorator.keywords:
        for kw in decorator.keywords:
            if kw.arg in ("path", None):
                path = _get_string_value(kw.value) or "<dynamic>"
                break
        else:
            path = "<dynamic>"
    else:
        path = "<dynamic>"

    return method.upper(), path


def _extract_depends(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[str]:
    """Return a list of dependency names injected via Depends(...) in function args."""
    deps: list[str] = []
    for arg_default in func_node.args.defaults + func_node.args.kw_defaults:
        if arg_default is None:
            continue
        if (
            isinstance(arg_default, ast.Call)
            and isinstance(arg_default.func, ast.Name)
            and arg_default.func.id == "Depends"
            and arg_default.args
        ):
            dep_arg = arg_default.args[0]
            if isinstance(dep_arg, ast.Name):
                deps.append(dep_arg.id)
            elif isinstance(dep_arg, ast.Attribute):
                deps.append(f"{ast.unparse(dep_arg)}")
    return deps


def _extract_annotation_name(annotation: ast.expr | None) -> str | None:
    """Extract a simple type name from an annotation node."""
    if annotation is None:
        return None
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Attribute):
        return annotation.attr
    # Subscript: Optional[X], list[X], etc. — unwrap outermost
    if isinstance(annotation, ast.Subscript):
        return _extract_annotation_name(annotation.slice)
    # Tuple/list of types inside a subscript
    if isinstance(annotation, ast.Tuple):
        for elt in annotation.elts:
            name = _extract_annotation_name(elt)
            if name:
                return name
    return None


class FastAPIExtractor:
    name = "fastapi"

    def contribute(
        self,
        parsed_modules: list[ParsedModule],
        builder: GraphBuilder,
        warnings: list[ScanWarning],
    ) -> None:
        # Build a lookup: local class name -> qualified name
        # so that type annotations on handler params can reference known models.
        class_lookup: dict[str, str] = {}
        for module in parsed_modules:
            for node in ast.walk(module.ast_tree):
                if isinstance(node, ast.ClassDef):
                    qname = f"{module.module_name}::{node.name}"
                    class_lookup[node.name] = qname

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

        for stmt in module.ast_tree.body:
            if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            for decorator in stmt.decorator_list:
                route = _extract_decorator_route(decorator)
                if route is None:
                    continue

                http_method, path = route
                endpoint_display = f"{http_method} {path}"

                # Ensure handler function node exists
                handler_qname = f"{module.module_name}::{stmt.name}"
                handler_id = _func_id(handler_qname)
                builder.add_node(
                    id=handler_id,
                    type=NodeType.FUNCTION,
                    name=stmt.name,
                    qualified_name=handler_qname,
                    display_name=handler_qname,
                    file_path=fp,
                    line_number=stmt.lineno,
                    certainty=Certainty.EXACT,
                )

                # Create ENDPOINT node
                ep_id = _endpoint_id(http_method, path)
                builder.add_node(
                    id=ep_id,
                    type=NodeType.ENDPOINT,
                    name=endpoint_display,
                    qualified_name=endpoint_display,
                    display_name=endpoint_display,
                    file_path=fp,
                    line_number=stmt.lineno,
                    certainty=Certainty.EXACT,
                    metadata={"http_method": http_method, "path": path},
                )

                # handler --EXPOSES_ENDPOINT--> endpoint
                builder.add_edge(
                    source_id=handler_id,
                    target_id=ep_id,
                    type=EdgeType.EXPOSES_ENDPOINT,
                    display_name=f"{stmt.name} exposes {endpoint_display}",
                    file_path=fp,
                    line_number=stmt.lineno,
                    certainty=Certainty.EXACT,
                )

                # Depends() injection
                deps = _extract_depends(stmt)
                for dep_name in deps:
                    dep_qname = class_lookup.get(dep_name, f"<unresolved>::{dep_name}")
                    dep_id = _func_id(dep_qname)
                    certainty = (
                        Certainty.EXACT if dep_name in class_lookup else Certainty.AMBIGUOUS
                    )
                    builder.add_node(
                        id=dep_id,
                        type=NodeType.FUNCTION,
                        name=dep_name,
                        qualified_name=dep_qname,
                        display_name=dep_qname,
                        certainty=certainty,
                    )
                    builder.add_edge(
                        source_id=handler_id,
                        target_id=dep_id,
                        type=EdgeType.INJECTS_DEPENDENCY,
                        display_name=f"{stmt.name} depends on {dep_name}",
                        file_path=fp,
                        line_number=stmt.lineno,
                        certainty=certainty,
                    )

                # Type annotations on parameters
                all_args = stmt.args.args + stmt.args.kwonlyargs
                if stmt.args.vararg:
                    all_args.append(stmt.args.vararg)
                if stmt.args.kwarg:
                    all_args.append(stmt.args.kwarg)

                for arg in all_args:
                    if arg.arg == "self":
                        continue
                    ann_name = _extract_annotation_name(arg.annotation)
                    if ann_name and ann_name in class_lookup:
                        cls_qname = class_lookup[ann_name]
                        cls_id = _func_id(cls_qname)
                        builder.add_edge(
                            source_id=handler_id,
                            target_id=cls_id,
                            type=EdgeType.TYPE_ANNOTATED,
                            display_name=f"{stmt.name} param annotated with {ann_name}",
                            file_path=fp,
                            line_number=stmt.lineno,
                            certainty=Certainty.EXACT,
                        )

                # Return type annotation
                ret_name = _extract_annotation_name(stmt.returns)
                if ret_name and ret_name in class_lookup:
                    cls_qname = class_lookup[ret_name]
                    cls_id = _func_id(cls_qname)
                    builder.add_edge(
                        source_id=handler_id,
                        target_id=cls_id,
                        type=EdgeType.TYPE_ANNOTATED,
                        display_name=f"{stmt.name} returns {ret_name}",
                        file_path=fp,
                        line_number=stmt.lineno,
                        certainty=Certainty.EXACT,
                    )

    def post_process(self, builder: GraphBuilder) -> None:
        pass
