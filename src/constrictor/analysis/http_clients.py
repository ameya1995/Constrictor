from __future__ import annotations

import ast

from constrictor.core.models import Certainty, ScanWarning
from constrictor.core.parser import ParsedModule
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.id_factory import create_id
from constrictor.graph.models import EdgeType, NodeType

_HTTP_METHODS = frozenset({"get", "post", "put", "delete", "patch", "options", "head"})
_HTTP_CLIENT_MODULES = frozenset({"requests", "httpx"})

# requests.Session().get(...) / httpx.Client().get(...)
_SESSION_CLASS_NAMES = frozenset({"Session", "Client", "AsyncClient"})


def _func_id(qualified_name: str) -> str:
    return create_id("func", qualified_name)


def _external_endpoint_id(url: str, method: str) -> str:
    return create_id("ext_endpoint", method.upper(), url)


def _get_string_value(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_dynamic_url(node: ast.expr | None) -> bool:
    """Return True if the node is an f-string or variable reference (not a plain string)."""
    if node is None:
        return True
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return False
    return True


def _enclosing_function_qname(
    module_name: str,
    call_node: ast.Call,
    func_map: dict[int, str],
) -> str:
    """Look up the enclosing function qualified name by node id."""
    return func_map.get(id(call_node), f"{module_name}::<module>")


def _build_func_map(
    module: ParsedModule,
) -> dict[int, str]:
    """Map every call node id -> enclosing function qualified name."""
    result: dict[int, str] = {}

    def _visit(
        stmts: list[ast.stmt],
        prefix: str,
    ) -> None:
        for stmt in stmts:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qname = f"{prefix}::{stmt.name}"
                for node in ast.walk(stmt):
                    if isinstance(node, ast.Call):
                        result[id(node)] = qname
                # Recurse for nested functions
                _visit(stmt.body, qname)
            elif isinstance(stmt, ast.ClassDef):
                cls_prefix = f"{prefix}::{stmt.name}"
                _visit(stmt.body, cls_prefix)

    _visit(module.ast_tree.body, module.module_name)
    return result


def _detect_http_call(
    node: ast.Call,
) -> tuple[str, str] | None:
    """Return (method, url_or_dynamic_marker) if the call is a requests/httpx HTTP call.

    Detected patterns:
    - requests.get(url)
    - httpx.post(url)
    - requests.Session().get(url)    [method call on a session instance]
    - httpx.Client().delete(url)
    """
    func = node.func
    if not isinstance(func, ast.Attribute):
        return None

    method = func.attr.lower()
    if method not in _HTTP_METHODS:
        return None

    caller = func.value

    # requests.get / httpx.post
    if isinstance(caller, ast.Name) and caller.id in _HTTP_CLIENT_MODULES:
        url_node = node.args[0] if node.args else None
        return method, (_get_string_value(url_node) or "<dynamic>")

    # requests.Session().get / httpx.Client().get
    if isinstance(caller, ast.Call):
        inner = caller.func
        if isinstance(inner, ast.Attribute) and inner.attr in _SESSION_CLASS_NAMES:
            if isinstance(inner.value, ast.Name) and inner.value.id in _HTTP_CLIENT_MODULES:
                url_node = node.args[0] if node.args else None
                return method, (_get_string_value(url_node) or "<dynamic>")

    return None


class HTTPClientExtractor:
    name = "http_clients"

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
        func_map = _build_func_map(module)

        for node in ast.walk(module.ast_tree):
            if not isinstance(node, ast.Call):
                continue
            result = _detect_http_call(node)
            if result is None:
                continue

            http_method, url = result
            is_dynamic = url == "<dynamic>"
            certainty = Certainty.AMBIGUOUS if is_dynamic else Certainty.EXACT

            ep_display = f"{http_method.upper()} {url}"
            ep_id = _external_endpoint_id(url, http_method)
            builder.add_node(
                id=ep_id,
                type=NodeType.EXTERNAL_ENDPOINT,
                name=ep_display,
                qualified_name=ep_display,
                display_name=ep_display,
                file_path=fp,
                line_number=node.lineno,
                certainty=certainty,
                metadata={"http_method": http_method.upper(), "url": url},
            )

            caller_qname = func_map.get(id(node), f"{module.module_name}::<module>")
            caller_id = _func_id(caller_qname)
            builder.add_node(
                id=caller_id,
                type=NodeType.FUNCTION,
                name=caller_qname.split("::")[-1],
                qualified_name=caller_qname,
                display_name=caller_qname,
                file_path=fp,
                certainty=Certainty.EXACT,
            )
            builder.add_edge(
                source_id=caller_id,
                target_id=ep_id,
                type=EdgeType.CALLS_HTTP,
                display_name=f"{caller_qname} calls {ep_display}",
                file_path=fp,
                line_number=node.lineno,
                certainty=certainty,
            )

    def post_process(self, builder: GraphBuilder) -> None:
        pass
