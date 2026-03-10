"""Shared tree-sitter traversal utilities for JS/TS extractors."""
from __future__ import annotations

from typing import Generator


def walk_nodes(node: object, *node_types: str) -> Generator[object, None, None]:
    """Yield all descendant nodes (incl. ``node``) matching any of the given types."""
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type in node_types:  # type: ignore[attr-defined]
            yield current
        stack.extend(reversed(current.children))  # type: ignore[attr-defined]


def get_text(node: object, source: bytes) -> str:
    """Return the UTF-8 decoded text of a tree-sitter node."""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")  # type: ignore[attr-defined]


def child_by_type(node: object, *type_names: str) -> object | None:
    """Return the first direct child whose type is in *type_names*, or None."""
    for child in node.children:  # type: ignore[attr-defined]
        if child.type in type_names:
            return child
    return None


def named_child_by_type(node: object, *type_names: str) -> object | None:
    """Return the first named child whose type is in *type_names*, or None."""
    for child in node.named_children:  # type: ignore[attr-defined]
        if child.type in type_names:
            return child
    return None


def get_string_value(node: object | None, source: bytes) -> str | None:
    """Extract the raw string content from a string / template_string node."""
    if node is None:
        return None
    if node.type in ("string", "template_string"):  # type: ignore[attr-defined]
        # Unwrap quotes / backticks
        raw = get_text(node, source)
        if len(raw) >= 2:
            return raw[1:-1]
    return None
