from __future__ import annotations

import ast

from constrictor.core.models import Certainty, ScanWarning
from constrictor.core.parser import ParsedModule
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.id_factory import create_id
from constrictor.graph.models import EdgeType, NodeType

_DJANGO_MODEL_BASES = frozenset({"Model", "models.Model"})
_DJANGO_RELATION_FIELDS = frozenset({"ForeignKey", "OneToOneField", "ManyToManyField"})
_URL_FUNCTIONS = frozenset({"path", "re_path", "url"})


def _endpoint_id(path: str, view: str) -> str:
    return create_id("endpoint", "DJANGO", path, view)


def _func_id(qualified_name: str) -> str:
    return create_id("func", qualified_name)


def _model_id(qualified_name: str) -> str:
    return create_id("model", qualified_name)


def _get_string_value(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _get_view_name(node: ast.expr) -> str | None:
    """Extract a view name from the second argument to path()/re_path()/url()."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return ast.unparse(node)
    if isinstance(node, ast.Call):
        # e.g. SomeView.as_view()
        return ast.unparse(node.func)
    return None


def _base_names(class_node: ast.ClassDef) -> list[str]:
    """Return simple string names for all base classes."""
    names: list[str] = []
    for base in class_node.bases:
        if isinstance(base, ast.Name):
            names.append(base.id)
        elif isinstance(base, ast.Attribute):
            names.append(ast.unparse(base))
    return names


def _is_django_model(class_node: ast.ClassDef) -> bool:
    return any(b in _DJANGO_MODEL_BASES for b in _base_names(class_node))


def _extract_foreign_key_target(call_node: ast.Call) -> str | None:
    """Extract the first argument of ForeignKey/OneToOneField/ManyToManyField."""
    if not call_node.args:
        return None
    arg = call_node.args[0]
    val = _get_string_value(arg)
    if val:
        return val
    if isinstance(arg, ast.Name):
        return arg.id
    if isinstance(arg, ast.Attribute):
        return ast.unparse(arg)
    return None


class DjangoExtractor:
    name = "django"

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
        is_urls_file = module.file_path.name == "urls.py"

        for stmt in module.ast_tree.body:
            # --- URL patterns in urls.py files ---
            if is_urls_file and isinstance(stmt, ast.Assign):
                # urlpatterns = [path(...), ...]
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and target.id == "urlpatterns":
                        self._extract_urlpatterns(stmt.value, module, builder, fp)

            # --- Django model classes ---
            if isinstance(stmt, ast.ClassDef) and _is_django_model(stmt):
                self._process_model(stmt, module, builder, fp)

    def _extract_urlpatterns(
        self,
        value: ast.expr,
        module: ParsedModule,
        builder: GraphBuilder,
        fp: str,
    ) -> None:
        """Walk a list/tuple literal for path()/re_path() calls."""
        if not isinstance(value, (ast.List, ast.Tuple)):
            return
        for elt in value.elts:
            self._extract_url_call(elt, module, builder, fp)

    def _extract_url_call(
        self,
        node: ast.expr,
        module: ParsedModule,
        builder: GraphBuilder,
        fp: str,
    ) -> None:
        if not isinstance(node, ast.Call):
            return
        func = node.func
        func_name: str | None = None
        if isinstance(func, ast.Name):
            func_name = func.id
        elif isinstance(func, ast.Attribute):
            func_name = func.attr

        if func_name not in _URL_FUNCTIONS:
            # Could be include() wrapping a list — recurse into args
            for arg in node.args:
                if isinstance(arg, (ast.List, ast.Tuple)):
                    for elt in arg.elts:
                        self._extract_url_call(elt, module, builder, fp)
            return

        if not node.args:
            return

        pattern = _get_string_value(node.args[0]) or "<dynamic>"
        view_name = "<unknown>"
        if len(node.args) >= 2:
            view_name = _get_view_name(node.args[1]) or "<unknown>"

        ep_display = f"DJANGO {pattern} -> {view_name}"
        ep_id = _endpoint_id(pattern, view_name)

        builder.add_node(
            id=ep_id,
            type=NodeType.ENDPOINT,
            name=ep_display,
            qualified_name=ep_display,
            display_name=ep_display,
            file_path=fp,
            line_number=node.lineno,
            certainty=Certainty.EXACT,
            metadata={"http_method": "ANY", "path": pattern, "view": view_name},
        )

        # Resolve view to a function/class node if detectable
        view_id = _func_id(f"{module.module_name}::{view_name}")
        builder.add_node(
            id=view_id,
            type=NodeType.FUNCTION,
            name=view_name,
            qualified_name=f"{module.module_name}::{view_name}",
            display_name=f"{module.module_name}::{view_name}",
            file_path=fp,
            line_number=node.lineno,
            certainty=Certainty.INFERRED,
        )
        builder.add_edge(
            source_id=view_id,
            target_id=ep_id,
            type=EdgeType.EXPOSES_ENDPOINT,
            display_name=f"{view_name} exposes {ep_display}",
            file_path=fp,
            line_number=node.lineno,
            certainty=Certainty.INFERRED,
        )

    def _process_model(
        self,
        class_node: ast.ClassDef,
        module: ParsedModule,
        builder: GraphBuilder,
        fp: str,
    ) -> None:
        model_qname = f"{module.module_name}::{class_node.name}"
        model_id = _model_id(model_qname)

        builder.add_node(
            id=model_id,
            type=NodeType.SQLALCHEMY_MODEL,
            name=class_node.name,
            qualified_name=model_qname,
            display_name=model_qname,
            file_path=fp,
            line_number=class_node.lineno,
            certainty=Certainty.EXACT,
            metadata={"framework": "django"},
        )

        for stmt in class_node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            if not isinstance(stmt.value, ast.Call):
                continue

            call = stmt.value
            call_name: str | None = None
            if isinstance(call.func, ast.Name):
                call_name = call.func.id
            elif isinstance(call.func, ast.Attribute):
                call_name = call.func.attr

            if call_name not in _DJANGO_RELATION_FIELDS:
                continue

            target = _extract_foreign_key_target(call)
            if not target:
                continue

            # Normalize "app.ModelName" -> "ModelName" for the display
            simple_target = target.split(".")[-1]
            target_qname = f"<unresolved>::{simple_target}"
            target_id = _func_id(target_qname)

            builder.add_node(
                id=target_id,
                type=NodeType.SQLALCHEMY_MODEL,
                name=simple_target,
                qualified_name=target_qname,
                display_name=target_qname,
                certainty=Certainty.AMBIGUOUS,
            )
            builder.add_edge(
                source_id=model_id,
                target_id=target_id,
                type=EdgeType.FOREIGN_KEY,
                display_name=f"{class_node.name} -> {simple_target} ({call_name})",
                file_path=fp,
                line_number=stmt.lineno,
                certainty=Certainty.INFERRED,
            )

    def post_process(self, builder: GraphBuilder) -> None:
        pass
