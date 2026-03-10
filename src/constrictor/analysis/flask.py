from __future__ import annotations

import ast

from constrictor.core.models import Certainty, ScanWarning
from constrictor.core.parser import ParsedModule
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.id_factory import create_id
from constrictor.graph.models import EdgeType, NodeType

_HTTP_METHODS = frozenset(
    {"GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"}
)
_DEFAULT_METHODS = ["GET"]


def _endpoint_id(method: str, path: str) -> str:
    return create_id("endpoint", method.upper(), path)


def _func_id(qualified_name: str) -> str:
    return create_id("func", qualified_name)


def _get_string_value(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _extract_methods_from_keyword(node: ast.Call) -> list[str]:
    """Extract HTTP methods list from @app.route(..., methods=["GET", "POST"])."""
    for kw in node.keywords:
        if kw.arg == "methods" and isinstance(kw.value, ast.List):
            methods: list[str] = []
            for elt in kw.value.elts:
                val = _get_string_value(elt)
                if val:
                    methods.append(val.upper())
            return methods if methods else _DEFAULT_METHODS
    return _DEFAULT_METHODS


def _extract_route_decorator(
    decorator: ast.expr,
) -> tuple[list[str], str] | None:
    """Return (methods, path) if decorator matches Flask @app.route / @bp.route pattern.

    Handles:
    - @app.route("/path")
    - @app.route("/path", methods=["GET", "POST"])
    - @blueprint.route("/path")
    """
    if not isinstance(decorator, ast.Call):
        return None
    func = decorator.func
    if not isinstance(func, ast.Attribute):
        return None
    if func.attr != "route":
        return None

    # First positional arg is the path
    if decorator.args:
        path = _get_string_value(decorator.args[0]) or "<dynamic>"
    else:
        path = "<dynamic>"

    methods = _extract_methods_from_keyword(decorator)
    return methods, path


class FlaskExtractor:
    name = "flask"

    def contribute(
        self,
        parsed_modules: list[ParsedModule],
        builder: GraphBuilder,
        warnings: list[ScanWarning],
    ) -> None:
        for module in parsed_modules:
            self._process_module(module, builder, warnings)

    def _process_module(
        self,
        module: ParsedModule,
        builder: GraphBuilder,
        warnings: list[ScanWarning],
    ) -> None:
        fp = str(module.file_path)

        for stmt in module.ast_tree.body:
            if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            for decorator in stmt.decorator_list:
                result = _extract_route_decorator(decorator)
                if result is None:
                    continue

                methods, path = result
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

                # Create one ENDPOINT node per method
                for method in methods:
                    endpoint_display = f"{method} {path}"
                    ep_id = _endpoint_id(method, path)

                    builder.add_node(
                        id=ep_id,
                        type=NodeType.ENDPOINT,
                        name=endpoint_display,
                        qualified_name=endpoint_display,
                        display_name=endpoint_display,
                        file_path=fp,
                        line_number=stmt.lineno,
                        certainty=Certainty.EXACT,
                        metadata={"http_method": method, "path": path},
                    )

                    builder.add_edge(
                        source_id=handler_id,
                        target_id=ep_id,
                        type=EdgeType.EXPOSES_ENDPOINT,
                        display_name=f"{stmt.name} exposes {endpoint_display}",
                        file_path=fp,
                        line_number=stmt.lineno,
                        certainty=Certainty.EXACT,
                    )

    def post_process(self, builder: GraphBuilder) -> None:
        pass
