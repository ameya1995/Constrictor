"""JS/TS function and call-graph extractor.

Handles:
- ``function`` declarations and expressions
- Arrow functions assigned to ``const``/``let``/``var``
- Class method definitions → ``JS_COMPONENT`` if the class looks like a React component
- ``CALLS`` edges between JS functions (best-effort: direct identifier calls only)
- ``CONTAINS`` edges from ``JS_MODULE`` → ``JS_FUNCTION`` / ``JS_COMPONENT``
"""
from __future__ import annotations

from constrictor.analysis.js_utils import get_text, walk_nodes
from constrictor.core.js_parser import ParsedJSModule
from constrictor.core.models import Certainty, ScanWarning
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.id_factory import create_id
from constrictor.graph.models import EdgeType, NodeType

_REACT_BASE_NAMES = frozenset({"Component", "PureComponent"})


def _module_id(module_name: str) -> str:
    return create_id("jsmod", module_name)


def _func_id(qualified_name: str) -> str:
    return create_id("jsfunc", qualified_name)


def _is_jsx_component(name: str) -> bool:
    """React convention: component names start with uppercase."""
    return bool(name) and name[0].isupper()


def _inherits_react(class_node: object, source: bytes) -> bool:
    """Return True if the class directly extends React.Component / PureComponent."""
    heritage = class_node.child_by_field_name("superclass")  # type: ignore[attr-defined]
    if heritage is None:
        return False
    text = get_text(heritage, source)
    for name in _REACT_BASE_NAMES:
        if name in text:
            return True
    return False


class JSCallExtractor:
    name = "js_calls"

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
        pass

    def _process_module(
        self,
        module: ParsedJSModule,
        builder: GraphBuilder,
        warnings: list[ScanWarning],
    ) -> None:
        fp = str(module.file_path)
        src = module.source
        mod_qname = module.module_name
        mod_id = _module_id(mod_qname)

        # Collect all top-level and nested function names so we can emit CALLS edges.
        # name → qualified_name
        func_registry: dict[str, str] = {}

        root = module.tree.root_node

        # ── Named function declarations ────────────────────────────────────
        for fn_node in walk_nodes(root, "function_declaration"):
            name_node = fn_node.child_by_field_name("name")
            if name_node is None:
                continue
            name = get_text(name_node, src)
            qname = f"{mod_qname}::{name}"
            func_registry[name] = qname
            is_comp = _is_jsx_component(name)
            node_type = NodeType.JS_COMPONENT if is_comp else NodeType.JS_FUNCTION
            fn_id = _func_id(qname)
            builder.add_node(
                id=fn_id,
                type=node_type,
                name=name,
                qualified_name=qname,
                display_name=qname,
                file_path=fp,
                line_number=fn_node.start_point[0] + 1,
                certainty=Certainty.EXACT,
            )
            builder.add_edge(
                source_id=mod_id,
                target_id=fn_id,
                type=EdgeType.CONTAINS,
                display_name=f"{mod_qname} contains {name}",
                file_path=fp,
                line_number=fn_node.start_point[0] + 1,
                certainty=Certainty.EXACT,
            )

        # ── Arrow functions and function expressions assigned to variables ─
        for lex_node in walk_nodes(root, "lexical_declaration", "variable_declaration"):
            for decl in walk_nodes(lex_node, "variable_declarator"):
                name_node = decl.child_by_field_name("name")
                value_node = decl.child_by_field_name("value")
                if name_node is None or value_node is None:
                    continue
                if value_node.type not in ("arrow_function", "function"):
                    continue
                name = get_text(name_node, src)
                qname = f"{mod_qname}::{name}"
                func_registry[name] = qname
                is_comp = _is_jsx_component(name)
                node_type = NodeType.JS_COMPONENT if is_comp else NodeType.JS_FUNCTION
                fn_id = _func_id(qname)
                builder.add_node(
                    id=fn_id,
                    type=node_type,
                    name=name,
                    qualified_name=qname,
                    display_name=qname,
                    file_path=fp,
                    line_number=lex_node.start_point[0] + 1,
                    certainty=Certainty.EXACT,
                )
                builder.add_edge(
                    source_id=mod_id,
                    target_id=fn_id,
                    type=EdgeType.CONTAINS,
                    display_name=f"{mod_qname} contains {name}",
                    file_path=fp,
                    line_number=lex_node.start_point[0] + 1,
                    certainty=Certainty.EXACT,
                )

        # ── Class declarations (React components) ─────────────────────────
        for cls_node in walk_nodes(root, "class_declaration"):
            name_node = cls_node.child_by_field_name("name")
            if name_node is None:
                continue
            cls_name = get_text(name_node, src)
            is_component = _is_jsx_component(cls_name) or _inherits_react(cls_node, src)
            node_type = NodeType.JS_COMPONENT if is_component else NodeType.JS_FUNCTION
            qname = f"{mod_qname}::{cls_name}"
            func_registry[cls_name] = qname
            cls_id = _func_id(qname)
            builder.add_node(
                id=cls_id,
                type=node_type,
                name=cls_name,
                qualified_name=qname,
                display_name=qname,
                file_path=fp,
                line_number=cls_node.start_point[0] + 1,
                certainty=Certainty.EXACT,
            )
            builder.add_edge(
                source_id=mod_id,
                target_id=cls_id,
                type=EdgeType.CONTAINS,
                display_name=f"{mod_qname} contains {cls_name}",
                file_path=fp,
                line_number=cls_node.start_point[0] + 1,
                certainty=Certainty.EXACT,
            )

            # Methods
            body = cls_node.child_by_field_name("body")
            if body:
                for method_node in walk_nodes(body, "method_definition"):
                    mname_node = method_node.child_by_field_name("name")
                    if mname_node is None:
                        continue
                    mname = get_text(mname_node, src)
                    mqname = f"{qname}::{mname}"
                    method_id = _func_id(mqname)
                    builder.add_node(
                        id=method_id,
                        type=NodeType.JS_FUNCTION,
                        name=mname,
                        qualified_name=mqname,
                        display_name=mqname,
                        file_path=fp,
                        line_number=method_node.start_point[0] + 1,
                        certainty=Certainty.EXACT,
                    )
                    builder.add_edge(
                        source_id=cls_id,
                        target_id=method_id,
                        type=EdgeType.CONTAINS,
                        display_name=f"{qname} contains {mname}",
                        file_path=fp,
                        line_number=method_node.start_point[0] + 1,
                        certainty=Certainty.EXACT,
                    )

        # ── CALLS edges (best-effort: direct identifier call expressions) ─
        for call_node in walk_nodes(root, "call_expression"):
            func_ref = call_node.child_by_field_name("function")
            if func_ref is None or func_ref.type != "identifier":
                continue
            callee_name = get_text(func_ref, src)
            if callee_name not in func_registry:
                continue
            callee_qname = func_registry[callee_name]
            callee_id = _func_id(callee_qname)
            builder.add_edge(
                source_id=mod_id,
                target_id=callee_id,
                type=EdgeType.CALLS,
                display_name=f"{mod_qname} calls {callee_qname}",
                file_path=fp,
                line_number=call_node.start_point[0] + 1,
                certainty=Certainty.INFERRED,
            )
