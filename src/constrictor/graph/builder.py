from __future__ import annotations

from constrictor.core.models import Certainty, ScanMetadata, ScanStatistics, ScanWarning
from constrictor.graph.id_factory import create_id
from constrictor.graph.models import (
    EdgeType,
    GraphDocument,
    GraphEdge,
    GraphNode,
    NodeType,
)


class GraphBuilder:
    """Accumulates nodes and edges, then builds a finalized GraphDocument."""

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[str, GraphEdge] = {}

    def add_node(
        self,
        id: str,
        type: NodeType,
        name: str,
        qualified_name: str = "",
        display_name: str = "",
        file_path: str | None = None,
        line_number: int | None = None,
        column: int | None = None,
        certainty: Certainty = Certainty.EXACT,
        metadata: dict[str, str] | None = None,
    ) -> GraphNode:
        """Add a node to the graph. If ID already exists, merge with higher certainty winning."""
        metadata = metadata or {}
        if id in self._nodes:
            existing = self._nodes[id]
            merged_certainty = max(existing.certainty, certainty)
            merged_metadata = _merge_metadata(existing.metadata, metadata)
            node = existing.model_copy(
                update={
                    "certainty": merged_certainty,
                    "metadata": merged_metadata,
                    "file_path": file_path or existing.file_path,
                    "line_number": line_number if line_number is not None else existing.line_number,
                    "column": column if column is not None else existing.column,
                }
            )
        else:
            node = GraphNode(
                id=id,
                type=type,
                name=name,
                qualified_name=qualified_name or name,
                display_name=display_name or name,
                file_path=file_path,
                line_number=line_number,
                column=column,
                certainty=certainty,
                metadata=metadata,
            )
        self._nodes[id] = node
        return node

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        type: EdgeType,
        display_name: str = "",
        file_path: str | None = None,
        line_number: int | None = None,
        certainty: Certainty = Certainty.EXACT,
        metadata: dict[str, str] | None = None,
    ) -> GraphEdge:
        """Add an edge to the graph. Auto-generates ID; merges if the same edge already exists."""
        metadata = metadata or {}
        edge_id = create_id("edge", source_id, target_id, type.value)
        if edge_id in self._edges:
            existing = self._edges[edge_id]
            merged_certainty = max(existing.certainty, certainty)
            merged_metadata = _merge_metadata(existing.metadata, metadata)
            edge = existing.model_copy(
                update={
                    "certainty": merged_certainty,
                    "metadata": merged_metadata,
                    "file_path": file_path or existing.file_path,
                    "line_number": line_number if line_number is not None else existing.line_number,
                }
            )
        else:
            edge = GraphEdge(
                id=edge_id,
                source_id=source_id,
                target_id=target_id,
                type=type,
                display_name=display_name or f"{source_id} -> {target_id}",
                file_path=file_path,
                line_number=line_number,
                certainty=certainty,
                metadata=metadata,
            )
        self._edges[edge_id] = edge
        return edge

    def build(
        self,
        scan_metadata: ScanMetadata | None = None,
        warnings: list[ScanWarning] | None = None,
    ) -> GraphDocument:
        """Finalize the graph: sort nodes/edges, compute statistics, separate unresolved warnings."""
        warnings = warnings or []
        sorted_nodes = sorted(self._nodes.values(), key=lambda n: n.id)
        sorted_edges = sorted(self._edges.values(), key=lambda e: e.id)

        node_type_counts: dict[str, int] = {}
        for node in sorted_nodes:
            node_type_counts[node.type.value] = node_type_counts.get(node.type.value, 0) + 1

        edge_type_counts: dict[str, int] = {}
        for edge in sorted_edges:
            edge_type_counts[edge.type.value] = edge_type_counts.get(edge.type.value, 0) + 1

        regular_warnings = [w for w in warnings if w.certainty != Certainty.UNRESOLVED]
        unresolved_warnings = [w for w in warnings if w.certainty == Certainty.UNRESOLVED]

        statistics = ScanStatistics(
            total_nodes=len(sorted_nodes),
            total_edges=len(sorted_edges),
            node_type_counts=node_type_counts,
            edge_type_counts=edge_type_counts,
            warning_count=len(warnings),
        )

        return GraphDocument(
            nodes=sorted_nodes,
            edges=sorted_edges,
            scan_metadata=scan_metadata,
            warnings=regular_warnings,
            unresolved=unresolved_warnings,
            statistics=statistics,
        )


def _merge_metadata(existing: dict[str, str], incoming: dict[str, str]) -> dict[str, str]:
    """Merge two metadata dicts. Existing keys preserved; conflicts concatenated with ' | '."""
    result = dict(existing)
    for key, value in incoming.items():
        if key in result:
            if result[key] != value:
                result[key] = f"{result[key]} | {value}"
        else:
            result[key] = value
    return result
