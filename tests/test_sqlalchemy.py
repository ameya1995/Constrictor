"""Tests for the SQLAlchemy extractor."""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

from constrictor.analysis.sqlalchemy import SQLAlchemyExtractor
from constrictor.core.models import ScanWarning
from constrictor.core.parser import ParsedModule
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.models import EdgeType, NodeType


def _make_module(module_name: str, source: str, file_path: str = "") -> ParsedModule:
    tree = ast.parse(textwrap.dedent(source))
    return ParsedModule(
        file_path=Path(file_path or f"/fake/{module_name.replace('.', '/')}.py"),
        module_name=module_name,
        ast_tree=tree,
    )


def _run(*modules: ParsedModule) -> tuple[GraphBuilder, list[ScanWarning]]:
    builder = GraphBuilder()
    warnings: list[ScanWarning] = []
    SQLAlchemyExtractor().contribute(list(modules), builder, warnings)
    return builder, warnings


# ---------------------------------------------------------------------------
# Base class detection
# ---------------------------------------------------------------------------

def test_declarative_base_detected():
    base_mod = _make_module("models.base", """
        from sqlalchemy.orm import declarative_base
        Base = declarative_base()
    """)
    user_mod = _make_module("models.user", """
        from models.base import Base
        from sqlalchemy import Column, Integer, String

        class User(Base):
            __tablename__ = "users"
            id = Column(Integer, primary_key=True)
            name = Column(String)
    """)
    builder, _ = _run(base_mod, user_mod)
    doc = builder.build()

    model_nodes = [n for n in doc.nodes if n.type == NodeType.SQLALCHEMY_MODEL]
    assert any(n.name == "User" for n in model_nodes)


def test_declarative_base_subclass_detected():
    """Classes inheriting from a user-defined Base subclass should be detected."""
    base_mod = _make_module("models.base", """
        from sqlalchemy.orm import DeclarativeBase

        class Base(DeclarativeBase):
            pass
    """)
    item_mod = _make_module("models.item", """
        from models.base import Base
        from sqlalchemy import Column, Integer, String

        class Item(Base):
            __tablename__ = "items"
            id = Column(Integer, primary_key=True)
    """)
    builder, _ = _run(base_mod, item_mod)
    doc = builder.build()

    model_nodes = [n for n in doc.nodes if n.type == NodeType.SQLALCHEMY_MODEL]
    assert any(n.name == "Item" for n in model_nodes)


# ---------------------------------------------------------------------------
# __tablename__ -> TABLE node
# ---------------------------------------------------------------------------

def test_tablename_creates_table_node():
    mod = _make_module("models.user", """
        from sqlalchemy.orm import declarative_base
        Base = declarative_base()

        from sqlalchemy import Column, Integer
        class User(Base):
            __tablename__ = "users"
            id = Column(Integer, primary_key=True)
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    table_nodes = [n for n in doc.nodes if n.type == NodeType.TABLE]
    assert any(n.name == "users" for n in table_nodes)


def test_defines_model_edge():
    mod = _make_module("models.user", """
        from sqlalchemy.orm import declarative_base
        Base = declarative_base()
        from sqlalchemy import Column, Integer
        class User(Base):
            __tablename__ = "users"
            id = Column(Integer, primary_key=True)
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    dm_edges = [e for e in doc.edges if e.type == EdgeType.DEFINES_MODEL]
    assert len(dm_edges) >= 1


# ---------------------------------------------------------------------------
# ForeignKey detection
# ---------------------------------------------------------------------------

def test_foreign_key_in_column_creates_edge():
    mod = _make_module("models.order", """
        from sqlalchemy.orm import declarative_base
        Base = declarative_base()
        from sqlalchemy import Column, Integer, ForeignKey
        class Order(Base):
            __tablename__ = "orders"
            id = Column(Integer, primary_key=True)
            user_id = Column(Integer, ForeignKey("users.id"))
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    fk_edges = [e for e in doc.edges if e.type == EdgeType.FOREIGN_KEY]
    assert len(fk_edges) >= 1

    # Target should be a TABLE node named "users"
    target_ids = {e.target_id for e in fk_edges}
    table_nodes = [n for n in doc.nodes if n.type == NodeType.TABLE and n.name == "users"]
    assert len(table_nodes) >= 1
    assert any(n.id in target_ids for n in table_nodes)


def test_standalone_foreign_key_call():
    """ForeignKey as a direct assignment (not nested in Column)."""
    mod = _make_module("models.post", """
        from sqlalchemy.orm import declarative_base
        Base = declarative_base()
        from sqlalchemy import Column, Integer, ForeignKey
        class Comment(Base):
            __tablename__ = "comments"
            id = Column(Integer, primary_key=True)
            post_id = Column(Integer, ForeignKey("posts.id"), nullable=False)
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    fk_edges = [e for e in doc.edges if e.type == EdgeType.FOREIGN_KEY]
    assert any("posts" in doc.nodes[
        next(i for i, n in enumerate(doc.nodes) if n.id == e.target_id)
    ].name for e in fk_edges)


# ---------------------------------------------------------------------------
# relationship() detection
# ---------------------------------------------------------------------------

def test_relationship_creates_calls_edge():
    mod = _make_module("models.user", """
        from sqlalchemy.orm import declarative_base, relationship
        Base = declarative_base()
        from sqlalchemy import Column, Integer, String
        class User(Base):
            __tablename__ = "users"
            id = Column(Integer, primary_key=True)
            orders = relationship("Order", back_populates="user")
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    rel_edges = [e for e in doc.edges if e.type == EdgeType.CALLS]
    assert len(rel_edges) >= 1


# ---------------------------------------------------------------------------
# Model metadata
# ---------------------------------------------------------------------------

def test_model_metadata_has_framework_sqlalchemy():
    mod = _make_module("models.item", """
        from sqlalchemy.orm import declarative_base
        Base = declarative_base()
        from sqlalchemy import Column, Integer
        class Item(Base):
            __tablename__ = "items"
            id = Column(Integer, primary_key=True)
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    model_nodes = [n for n in doc.nodes if n.type == NodeType.SQLALCHEMY_MODEL]
    assert any(n.metadata.get("framework") == "sqlalchemy" for n in model_nodes)


def test_non_model_class_ignored():
    mod = _make_module("app.service", """
        class UserService:
            def create(self): pass
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    model_nodes = [n for n in doc.nodes if n.type == NodeType.SQLALCHEMY_MODEL]
    assert len(model_nodes) == 0
