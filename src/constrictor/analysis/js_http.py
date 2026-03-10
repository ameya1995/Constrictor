"""JS/TS HTTP call extractor + cross-language edge stitcher.

Detects frontend HTTP calls:
- ``fetch("/api/...")``
- ``axios.get("/api/...")`` / ``axios.post(...)`` etc.
- ``axios({ url: "/api/..." })``
- ``useQuery(...)`` (React Query) — extracts the URL string argument
- ``useSWR("/api/...")`` — first argument is the cache key / URL

Cross-language stitching (``post_process``):
- After all extractors have run, matches each frontend ``CALLS_HTTP`` edge's
  target URL against backend ``ENDPOINT`` node path metadata.
- Matched pairs get a direct ``CALLS_HTTP`` edge: JS_FUNCTION → ENDPOINT.
- Unmatched calls remain as ``CALLS_HTTP`` → ``EXTERNAL_ENDPOINT`` (AMBIGUOUS).
"""
from __future__ import annotations

import re

from constrictor.analysis.js_utils import get_text, walk_nodes
from constrictor.core.js_parser import ParsedJSModule
from constrictor.core.models import Certainty, ScanWarning
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.id_factory import create_id
from constrictor.graph.models import EdgeType, NodeType

_AXIOS_METHODS = frozenset(
    {"get", "post", "put", "delete", "patch", "options", "head", "request"}
)
_HOOK_NAMES = frozenset({"useQuery", "useSWR", "useMutation"})

# Matches a plain string literal (single, double, or backtick — no interpolation)
_PLAIN_STRING_RE = re.compile(r'^["\'](.+)["\']$|^`([^`${}]+)`$')


def _module_id(module_name: str) -> str:
    return create_id("jsmod", module_name)


def _func_id(qualified_name: str) -> str:
    return create_id("jsfunc", qualified_name)


def _external_endpoint_id(url: str, method: str) -> str:
    return create_id("js_ext_endpoint", method.upper(), url)


def _normalize_url(url: str) -> str:
    """Strip query params and normalise trailing slashes for matching."""
    url = url.split("?")[0].split("#")[0].rstrip("/")
    return url


def _extract_string(node: object | None, source: bytes) -> str | None:
    """Return the string value of a string / template_string node, or None."""
    if node is None:
        return None
    if node.type == "string":  # type: ignore[attr-defined]
        raw = source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")  # type: ignore[attr-defined]
        if len(raw) >= 2:
            return raw[1:-1]
    if node.type == "template_string":  # type: ignore[attr-defined]
        raw = source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")  # type: ignore[attr-defined]
        # Template strings may have interpolations; treat plain ones as static
        if "${" not in raw:
            return raw[1:-1]
    return None


def _enclosing_function(
    call_node: object, root: object, source: bytes, mod_qname: str
) -> str:
    """Walk ancestors to find the nearest enclosing function/arrow/method name."""
    node = call_node.parent  # type: ignore[attr-defined]
    while node is not None:
        if node.type in ("function_declaration", "function"):
            name_node = node.child_by_field_name("name")  # type: ignore[attr-defined]
            if name_node:
                return f"{mod_qname}::{get_text(name_node, source)}"
        if node.type == "method_definition":
            name_node = node.child_by_field_name("name")  # type: ignore[attr-defined]
            if name_node:
                return f"{mod_qname}::{get_text(name_node, source)}"
        if node.type == "variable_declarator":
            name_node = node.child_by_field_name("name")  # type: ignore[attr-defined]
            if name_node:
                return f"{mod_qname}::{get_text(name_node, source)}"
        node = node.parent  # type: ignore[attr-defined]
    return f"{mod_qname}::<module>"


class JSHttpExtractor:
    name = "js_http"

    def contribute_js(
        self,
        parsed_modules: list[ParsedJSModule],
        builder: GraphBuilder,
        warnings: list[ScanWarning],
    ) -> None:
        for module in parsed_modules:
            self._process_module(module, builder, warnings)

    def contribute(
        self,
        parsed_modules: object,
        builder: GraphBuilder,
        warnings: list[ScanWarning],
    ) -> None:
        pass

    def post_process(self, builder: GraphBuilder) -> None:
        """Stitch frontend CALLS_HTTP edges to backend ENDPOINT nodes."""
        _stitch_cross_language_edges(builder)

    def _process_module(
        self,
        module: ParsedJSModule,
        builder: GraphBuilder,
        warnings: list[ScanWarning],
    ) -> None:
        fp = str(module.file_path)
        src = module.source
        mod_qname = module.module_name
        root = module.tree.root_node

        for call_node in walk_nodes(root, "call_expression"):
            result = _detect_http_call(call_node, src)
            if result is None:
                continue

            method, url = result
            is_dynamic = url == "<dynamic>"
            certainty = Certainty.AMBIGUOUS if is_dynamic else Certainty.EXACT

            ep_display = f"{method.upper()} {url}"
            ep_id = _external_endpoint_id(url, method)
            builder.add_node(
                id=ep_id,
                type=NodeType.EXTERNAL_ENDPOINT,
                name=ep_display,
                qualified_name=ep_display,
                display_name=ep_display,
                file_path=None,
                line_number=call_node.start_point[0] + 1,  # type: ignore[attr-defined]
                certainty=certainty,
                metadata={"http_method": method.upper(), "url": url, "source": "js"},
            )

            caller_qname = _enclosing_function(call_node, root, src, mod_qname)
            caller_id = _func_id(caller_qname)
            builder.add_node(
                id=caller_id,
                type=NodeType.JS_FUNCTION,
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
                line_number=call_node.start_point[0] + 1,  # type: ignore[attr-defined]
                certainty=certainty,
                metadata={"url": url, "http_method": method.upper()},
            )


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

def _detect_http_call(call_node: object, source: bytes) -> tuple[str, str] | None:
    """Return (method, url_or_<dynamic>) if the call is a frontend HTTP call."""
    func = call_node.child_by_field_name("function")  # type: ignore[attr-defined]
    if func is None:
        return None

    func_text = get_text(func, source)
    args_node = call_node.child_by_field_name("arguments")  # type: ignore[attr-defined]

    # ── fetch(url) ────────────────────────────────────────────────────────
    if func_text == "fetch":
        if args_node is None:
            return None
        first_arg = args_node.named_children[0] if args_node.named_children else None  # type: ignore[attr-defined]
        url = _extract_string(first_arg, source) or "<dynamic>"
        return "GET", url

    # ── axios.get(url) / axios.post(url) etc. ─────────────────────────────
    if func.type == "member_expression":  # type: ignore[attr-defined]
        obj = func.child_by_field_name("object")  # type: ignore[attr-defined]
        prop = func.child_by_field_name("property")  # type: ignore[attr-defined]
        if obj is None or prop is None:
            return None
        obj_text = get_text(obj, source)
        method = get_text(prop, source).lower()
        if obj_text == "axios" and method in _AXIOS_METHODS:
            if args_node is None:
                return None
            nc = args_node.named_children  # type: ignore[attr-defined]
            first_arg = nc[0] if nc else None
            url = _extract_string(first_arg, source) or "<dynamic>"
            http_method = "GET" if method in ("get", "request") else method.upper()
            return http_method, url

    # ── axios({ url: '/api/...' }) ────────────────────────────────────────
    if func_text == "axios":
        if args_node is None:
            return None
        first_arg = args_node.named_children[0] if args_node.named_children else None  # type: ignore[attr-defined]
        if first_arg is None or first_arg.type != "object":  # type: ignore[attr-defined]
            return None
        url = _extract_object_prop(first_arg, "url", source)
        method_val = _extract_object_prop(first_arg, "method", source)
        http_method = (method_val.upper() if method_val else "GET")
        return http_method, (url or "<dynamic>")

    # ── useQuery(['key', url]) / useQuery(url) ────────────────────────────
    if func_text in _HOOK_NAMES:
        if args_node is None:
            return None
        first_arg = args_node.named_children[0] if args_node.named_children else None  # type: ignore[attr-defined]
        url = _extract_string(first_arg, source)
        if url is None and first_arg is not None and first_arg.type == "array":  # type: ignore[attr-defined]
            # useQuery(["key", url, ...]) pattern
            elems = first_arg.named_children  # type: ignore[attr-defined]
            if len(elems) >= 2:
                url = _extract_string(elems[1], source)
        return "GET", (url or "<dynamic>")

    # ── useSWR(url) ───────────────────────────────────────────────────────
    if func_text == "useSWR":
        if args_node is None:
            return None
        first_arg = args_node.named_children[0] if args_node.named_children else None  # type: ignore[attr-defined]
        url = _extract_string(first_arg, source) or "<dynamic>"
        return "GET", url

    return None


def _extract_object_prop(obj_node: object, prop_name: str, source: bytes) -> str | None:
    """Extract the string value of a named property from an object literal node."""
    for pair in walk_nodes(obj_node, "pair"):
        key_node = pair.child_by_field_name("key")  # type: ignore[attr-defined]
        val_node = pair.child_by_field_name("value")  # type: ignore[attr-defined]
        if key_node is None or val_node is None:
            continue
        key_text = get_text(key_node, source).strip("\"'")
        if key_text == prop_name:
            return _extract_string(val_node, source)
    return None


# ---------------------------------------------------------------------------
# Cross-language stitching
# ---------------------------------------------------------------------------

def _stitch_cross_language_edges(builder: GraphBuilder) -> None:
    """Match JS frontend HTTP calls to Python backend ENDPOINT nodes.

    For every ``CALLS_HTTP`` edge whose target is an ``EXTERNAL_ENDPOINT`` with
    ``source=js`` in its metadata, try to find a backend ``ENDPOINT`` node whose
    ``path`` metadata matches the URL.  When a match is found:
    - The original ``EXTERNAL_ENDPOINT`` node stays (so the edge still exists)
    - An additional direct ``CALLS_HTTP`` edge is added from the JS caller to the
      Python ENDPOINT node.
    """
    # Build a lookup: normalised_path → list[endpoint_node_id]
    endpoint_map: dict[str, list[str]] = {}
    for node in builder._nodes.values():  # type: ignore[attr-defined]
        if node.type == NodeType.ENDPOINT:
            path = node.metadata.get("path", "")
            if path:
                normalised = _normalize_url(path)
                endpoint_map.setdefault(normalised, []).append(node.id)

    if not endpoint_map:
        return

    # Walk CALLS_HTTP edges from JS callers
    edges_to_add: list[dict] = []
    for edge in list(builder._edges.values()):  # type: ignore[attr-defined]
        if edge.type != EdgeType.CALLS_HTTP:
            continue
        target_node = builder._nodes.get(edge.target_id)  # type: ignore[attr-defined]
        if target_node is None or target_node.type != NodeType.EXTERNAL_ENDPOINT:
            continue
        if target_node.metadata.get("source") != "js":
            continue

        url = target_node.metadata.get("url", "")
        if url == "<dynamic>":
            continue

        normalised = _normalize_url(url)
        matched_ids = endpoint_map.get(normalised, [])

        for backend_ep_id in matched_ids:
            edges_to_add.append({
                "source_id": edge.source_id,
                "target_id": backend_ep_id,
                "type": EdgeType.CALLS_HTTP,
                "display_name": f"{edge.display_name} [cross-language]",
                "file_path": edge.file_path,
                "line_number": edge.line_number,
                "certainty": Certainty.INFERRED,
                "metadata": {"stitched": "true", "url": url},
            })

    for kwargs in edges_to_add:
        builder.add_edge(**kwargs)
