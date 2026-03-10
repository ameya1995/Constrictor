"""Output formatting helpers for compact and files-only views.

Three modes:
  full    -- raw model dicts (default, most verbose)
  compact -- (qualified_name, type, file:line) for nodes; (src -> tgt [TYPE]) for edges
  files   -- deduplicated sorted list of file paths
"""
from __future__ import annotations

from typing import Any

from constrictor.graph.models import GraphEdge, GraphNode

OutputFormat = str  # Literal["full", "compact", "files"]


def format_nodes(
    nodes: list[GraphNode],
    fmt: OutputFormat = "full",
) -> Any:
    """Render a list of GraphNode objects according to *fmt*."""
    if fmt == "files":
        return sorted({n.file_path for n in nodes if n.file_path})

    if fmt == "compact":
        result = []
        for n in nodes:
            loc = ""
            if n.file_path:
                loc = n.file_path
                if n.line_number is not None:
                    loc = f"{loc}:{n.line_number}"
            result.append(
                {
                    "qualified_name": n.qualified_name,
                    "type": n.type.value,
                    "location": loc,
                }
            )
        return result

    # full
    return [n.model_dump() for n in nodes]


def format_edges(
    edges: list[GraphEdge],
    fmt: OutputFormat = "full",
) -> Any:
    """Render a list of GraphEdge objects according to *fmt*."""
    if fmt == "files":
        return sorted({e.file_path for e in edges if e.file_path})

    if fmt == "compact":
        return [
            {
                "display": e.display_name,
                "type": e.type.value,
                "certainty": e.certainty.name,
            }
            for e in edges
        ]

    # full
    return [e.model_dump() for e in edges]


def format_subgraph(
    focus_node: GraphNode,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    fmt: OutputFormat = "full",
) -> dict[str, Any]:
    """Render the three parts of a subgraph result according to *fmt*."""
    if fmt == "files":
        all_nodes = [focus_node, *nodes]
        files = sorted({n.file_path for n in all_nodes if n.file_path})
        return {
            "focus": focus_node.qualified_name,
            "affected_file_count": len(files),
            "affected_files": files,
        }

    if fmt == "compact":
        return {
            "focus": {
                "qualified_name": focus_node.qualified_name,
                "type": focus_node.type.value,
                "location": _node_loc(focus_node),
            },
            "affected_node_count": len(nodes),
            "nodes": format_nodes(nodes, fmt="compact"),
            "edges": format_edges(edges, fmt="compact"),
        }

    return {
        "focus_node": focus_node.model_dump(),
        "affected_node_count": len(nodes),
        "affected_edge_count": len(edges),
        "nodes": [n.model_dump() for n in nodes],
        "edges": [e.model_dump() for e in edges],
    }


def _node_loc(node: GraphNode) -> str:
    if not node.file_path:
        return ""
    if node.line_number is not None:
        return f"{node.file_path}:{node.line_number}"
    return node.file_path


VALID_FORMATS: frozenset[str] = frozenset({"full", "compact", "files"})


def validate_format(fmt: str) -> str:
    """Return *fmt* if valid, raise ValueError otherwise."""
    if fmt not in VALID_FORMATS:
        raise ValueError(
            f"Invalid format {fmt!r}. Must be one of: {', '.join(sorted(VALID_FORMATS))}"
        )
    return fmt
