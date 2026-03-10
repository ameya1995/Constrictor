"""Tests for the Django extractor."""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

from constrictor.analysis.django import DjangoExtractor
from constrictor.core.models import ScanWarning
from constrictor.core.parser import ParsedModule
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.models import EdgeType, NodeType


def _make_module(module_name: str, source: str, file_path: str = "") -> ParsedModule:
    tree = ast.parse(textwrap.dedent(source))
    fp = file_path or f"/fake/{module_name.replace('.', '/')}.py"
    return ParsedModule(
        file_path=Path(fp),
        module_name=module_name,
        ast_tree=tree,
    )


def _make_urls_module(module_name: str, source: str) -> ParsedModule:
    """Helper to create a urls.py module (filename matters for Django detection)."""
    base = "/fake/" + module_name.replace(".", "/")
    fp = base.rsplit("/", 1)[0] + "/urls.py"
    tree = ast.parse(textwrap.dedent(source))
    return ParsedModule(
        file_path=Path(fp),
        module_name=module_name,
        ast_tree=tree,
    )


def _run(*modules: ParsedModule) -> tuple[GraphBuilder, list[ScanWarning]]:
    builder = GraphBuilder()
    warnings: list[ScanWarning] = []
    DjangoExtractor().contribute(list(modules), builder, warnings)
    return builder, warnings


# ---------------------------------------------------------------------------
# URL pattern detection
# ---------------------------------------------------------------------------

def test_path_creates_endpoint_node():
    mod = _make_urls_module("myapp.urls", """
        from django.urls import path
        from myapp.views import home

        urlpatterns = [
            path("home/", home),
        ]
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    ep_nodes = [n for n in doc.nodes if n.type == NodeType.ENDPOINT]
    assert len(ep_nodes) >= 1
    assert any("home/" in n.metadata.get("path", "") for n in ep_nodes)


def test_re_path_creates_endpoint():
    mod = _make_urls_module("myapp.urls", """
        from django.urls import re_path
        from myapp.views import detail

        urlpatterns = [
            re_path(r"^items/(?P<pk>[0-9]+)/$", detail),
        ]
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    ep_nodes = [n for n in doc.nodes if n.type == NodeType.ENDPOINT]
    assert len(ep_nodes) >= 1


def test_multiple_url_patterns():
    mod = _make_urls_module("myapp.urls", """
        from django.urls import path
        from myapp import views

        urlpatterns = [
            path("users/", views.list_users),
            path("users/<int:pk>/", views.user_detail),
            path("orders/", views.list_orders),
        ]
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    ep_nodes = [n for n in doc.nodes if n.type == NodeType.ENDPOINT]
    assert len(ep_nodes) == 3


def test_non_urls_file_not_processed():
    """path() calls in non-urls.py files should not create endpoints."""
    mod = _make_module("myapp.utils", """
        from django.urls import path

        def build_path():
            return path("test/", None)
    """, file_path="/fake/myapp/utils.py")
    builder, _ = _run(mod)
    doc = builder.build()

    ep_nodes = [n for n in doc.nodes if n.type == NodeType.ENDPOINT]
    assert len(ep_nodes) == 0


# ---------------------------------------------------------------------------
# Django model detection
# ---------------------------------------------------------------------------

def test_model_subclass_creates_sqlalchemy_model_node():
    mod = _make_module("myapp.models", """
        from django.db import models

        class Article(models.Model):
            title = models.CharField(max_length=200)
            body = models.TextField()
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    model_nodes = [n for n in doc.nodes if n.type == NodeType.SQLALCHEMY_MODEL]
    assert len(model_nodes) >= 1
    assert any(n.name == "Article" for n in model_nodes)


def test_model_metadata_has_framework_django():
    mod = _make_module("myapp.models", """
        from django.db import models

        class Post(models.Model):
            pass
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    model_nodes = [n for n in doc.nodes if n.type == NodeType.SQLALCHEMY_MODEL]
    assert any(n.metadata.get("framework") == "django" for n in model_nodes)


def test_foreign_key_creates_edge():
    mod = _make_module("myapp.models", """
        from django.db import models

        class Comment(models.Model):
            post = models.ForeignKey("Post", on_delete=models.CASCADE)
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    fk_edges = [e for e in doc.edges if e.type == EdgeType.FOREIGN_KEY]
    assert len(fk_edges) >= 1


def test_many_to_many_field_creates_edge():
    mod = _make_module("myapp.models", """
        from django.db import models

        class Post(models.Model):
            tags = models.ManyToManyField("Tag")
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    fk_edges = [e for e in doc.edges if e.type == EdgeType.FOREIGN_KEY]
    assert len(fk_edges) >= 1


def test_non_model_class_not_extracted():
    mod = _make_module("myapp.forms", """
        class MyForm:
            pass
    """)
    builder, _ = _run(mod)
    doc = builder.build()

    model_nodes = [n for n in doc.nodes if n.type == NodeType.SQLALCHEMY_MODEL]
    assert len(model_nodes) == 0
