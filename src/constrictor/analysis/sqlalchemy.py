from __future__ import annotations

import ast

from constrictor.core.models import Certainty, ScanWarning
from constrictor.core.parser import ParsedModule
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.id_factory import create_id
from constrictor.graph.models import EdgeType, NodeType

# Names that commonly identify declarative bases
_DECLARATIVE_BASE_NAMES = frozenset({
    "Base", "DeclarativeBase", "DeclarativeBaseNoMeta",
    "MappedAsDataclass",
})


def _model_id(qualified_name: str) -> str:
    return create_id("model", qualified_name)


def _table_id(table_name: str) -> str:
    return create_id("table", table_name)


def _func_id(qualified_name: str) -> str:
    return create_id("func", qualified_name)


def _get_string_value(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _base_names(class_node: ast.ClassDef) -> list[str]:
    names: list[str] = []
    for base in class_node.bases:
        if isinstance(base, ast.Name):
            names.append(base.id)
        elif isinstance(base, ast.Attribute):
            names.append(base.attr)
    return names


def _is_sqlalchemy_model(
    class_node: ast.ClassDef,
    base_class_names: set[str],
) -> bool:
    """Return True if the class inherits from a known SQLAlchemy declarative base."""
    for name in _base_names(class_node):
        if name in _DECLARATIVE_BASE_NAMES or name in base_class_names:
            return True
    return False


def _collect_base_class_names(parsed_modules: list[ParsedModule]) -> set[str]:
    """Find names assigned via declarative_base() or DeclarativeBase subclasses."""
    bases: set[str] = set()
    for module in parsed_modules:
        for node in ast.walk(module.ast_tree):
            # Base = declarative_base()
            if isinstance(node, ast.Assign):
                if isinstance(node.value, ast.Call):
                    call = node.value
                    call_name: str | None = None
                    if isinstance(call.func, ast.Name):
                        call_name = call.func.id
                    elif isinstance(call.func, ast.Attribute):
                        call_name = call.func.attr
                    if call_name in {"declarative_base", "as_declarative"}:
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                bases.add(target.id)
            # class Base(DeclarativeBase): ...
            if isinstance(node, ast.ClassDef):
                if any(b in _DECLARATIVE_BASE_NAMES for b in _base_names(node)):
                    bases.add(node.name)
    return bases


class SQLAlchemyExtractor:
    name = "sqlalchemy"

    def contribute(
        self,
        parsed_modules: list[ParsedModule],
        builder: GraphBuilder,
        warnings: list[ScanWarning],
    ) -> None:
        base_class_names = _collect_base_class_names(parsed_modules)

        for module in parsed_modules:
            self._process_module(module, builder, warnings, base_class_names)

    def _process_module(
        self,
        module: ParsedModule,
        builder: GraphBuilder,
        warnings: list[ScanWarning],
        base_class_names: set[str],
    ) -> None:
        fp = str(module.file_path)

        for stmt in module.ast_tree.body:
            if not isinstance(stmt, ast.ClassDef):
                continue
            if not _is_sqlalchemy_model(stmt, base_class_names):
                continue

            self._process_model(stmt, module, builder, fp)

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
            metadata={"framework": "sqlalchemy"},
        )

        # Look for __tablename__
        tablename: str | None = None
        for stmt in class_node.body:
            if (
                isinstance(stmt, ast.Assign)
                and any(
                    isinstance(t, ast.Name) and t.id == "__tablename__"
                    for t in stmt.targets
                )
            ):
                tablename = _get_string_value(stmt.value)
                break

        if tablename:
            table_id = _table_id(tablename)
            builder.add_node(
                id=table_id,
                type=NodeType.TABLE,
                name=tablename,
                qualified_name=tablename,
                display_name=tablename,
                file_path=fp,
                line_number=class_node.lineno,
                certainty=Certainty.EXACT,
            )
            builder.add_edge(
                source_id=model_id,
                target_id=table_id,
                type=EdgeType.DEFINES_MODEL,
                display_name=f"{class_node.name} defines table {tablename}",
                file_path=fp,
                line_number=class_node.lineno,
                certainty=Certainty.EXACT,
            )

        # Walk class body for Column / relationship / mapped_column
        for stmt in class_node.body:
            self._process_body_stmt(stmt, model_id, model_qname, class_node, module, builder, fp)

    def _process_body_stmt(
        self,
        stmt: ast.stmt,
        model_id: str,
        model_qname: str,
        class_node: ast.ClassDef,
        module: ParsedModule,
        builder: GraphBuilder,
        fp: str,
    ) -> None:
        # Assignments like: id = Column(Integer, ...) or name: Mapped[str] = mapped_column(...)
        value: ast.expr | None = None
        line: int = stmt.lineno if hasattr(stmt, "lineno") else 0

        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
            value = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.value, ast.Call):
            value = stmt.value

        if value is None or not isinstance(value, ast.Call):
            return

        call = value
        call_name: str | None = None
        if isinstance(call.func, ast.Name):
            call_name = call.func.id
        elif isinstance(call.func, ast.Attribute):
            call_name = call.func.attr

        if call_name in {"Column", "mapped_column"}:
            # Look for ForeignKey inside Column args
            for arg in call.args:
                self._check_foreign_key(arg, model_id, class_node, module, builder, fp, line)
            for kw in call.keywords:
                self._check_foreign_key(kw.value, model_id, class_node, module, builder, fp, line)

        elif call_name == "ForeignKey":
            self._handle_foreign_key_call(call, model_id, class_node, builder, fp, line)

        elif call_name == "relationship":
            # relationship("OtherModel", ...) or relationship(OtherModel, ...)
            if call.args:
                target = _get_string_value(call.args[0])
                if target is None and isinstance(call.args[0], ast.Name):
                    target = call.args[0].id
                if target:
                    target_qname = f"<unresolved>::{target}"
                    target_id = _func_id(target_qname)
                    builder.add_node(
                        id=target_id,
                        type=NodeType.SQLALCHEMY_MODEL,
                        name=target,
                        qualified_name=target_qname,
                        display_name=target_qname,
                        certainty=Certainty.AMBIGUOUS,
                    )
                    builder.add_edge(
                        source_id=model_id,
                        target_id=target_id,
                        type=EdgeType.CALLS,
                        display_name=f"{class_node.name} relationship -> {target}",
                        file_path=fp,
                        line_number=line,
                        certainty=Certainty.INFERRED,
                    )

    def _check_foreign_key(
        self,
        node: ast.expr,
        model_id: str,
        class_node: ast.ClassDef,
        module: ParsedModule,
        builder: GraphBuilder,
        fp: str,
        line: int,
    ) -> None:
        """Recursively check if a node is or contains a ForeignKey() call."""
        if isinstance(node, ast.Call):
            call_name: str | None = None
            if isinstance(node.func, ast.Name):
                call_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                call_name = node.func.attr
            if call_name == "ForeignKey":
                self._handle_foreign_key_call(node, model_id, class_node, builder, fp, line)
                return
            # recurse into args
            for arg in node.args:
                self._check_foreign_key(arg, model_id, class_node, module, builder, fp, line)

    def _handle_foreign_key_call(
        self,
        call: ast.Call,
        model_id: str,
        class_node: ast.ClassDef,
        builder: GraphBuilder,
        fp: str,
        line: int,
    ) -> None:
        if not call.args:
            return
        ref = _get_string_value(call.args[0])
        if not ref:
            return
        # ref is typically "other_table.id" or "other_table"
        table_name = ref.split(".")[0]
        target_id = _table_id(table_name)
        builder.add_node(
            id=target_id,
            type=NodeType.TABLE,
            name=table_name,
            qualified_name=table_name,
            display_name=table_name,
            certainty=Certainty.INFERRED,
        )
        builder.add_edge(
            source_id=model_id,
            target_id=target_id,
            type=EdgeType.FOREIGN_KEY,
            display_name=f"{class_node.name} FK -> {table_name}",
            file_path=fp,
            line_number=line,
            certainty=Certainty.EXACT,
        )

    def post_process(self, builder: GraphBuilder) -> None:
        pass
