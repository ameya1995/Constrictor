from __future__ import annotations

from collections import deque
from typing import Literal

import networkx as nx

from constrictor.core.models import Certainty
from constrictor.graph.models import (
    AmbiguousReview,
    GraphDocument,
    GraphEdge,
    GraphNode,
    GraphPath,
    GraphPathResult,
    GraphSubgraph,
)


class NodeNotFoundError(Exception):
    """Raised when a node cannot be resolved by ID or name."""


class GraphQueryEngine:
    """Query engine for impact analysis and path finding on a GraphDocument."""

    def __init__(self, document: GraphDocument) -> None:
        self._document = document
        self._nodes_by_id: dict[str, GraphNode] = {n.id: n for n in document.nodes}
        self._edges_by_id: dict[str, GraphEdge] = {e.id: e for e in document.edges}

        self._outgoing: dict[str, list[GraphEdge]] = {n.id: [] for n in document.nodes}
        self._incoming: dict[str, list[GraphEdge]] = {n.id: [] for n in document.nodes}
        for edge in document.edges:
            if edge.source_id in self._outgoing:
                self._outgoing[edge.source_id].append(edge)
            if edge.target_id in self._incoming:
                self._incoming[edge.target_id].append(edge)

        self._nx_graph: nx.DiGraph = nx.DiGraph()
        for node in document.nodes:
            self._nx_graph.add_node(node.id)
        for edge in document.edges:
            self._nx_graph.add_edge(edge.source_id, edge.target_id, edge_id=edge.id)

    def resolve_node(self, id_or_name: str) -> GraphNode:
        """Resolve a node by ID or name.

        Resolution order:
        1. Exact ID match
        2. display_name exact match (case-insensitive)
        3. qualified_name contains match
        4. display_name contains match (fuzzy)
        """
        if id_or_name in self._nodes_by_id:
            return self._nodes_by_id[id_or_name]

        lower = id_or_name.lower()

        for node in self._document.nodes:
            if node.display_name.lower() == lower:
                return node

        for node in self._document.nodes:
            if lower in node.qualified_name.lower():
                return node

        for node in self._document.nodes:
            if lower in node.display_name.lower():
                return node

        raise NodeNotFoundError(
            f"No node found matching {id_or_name!r}. "
            "Try using an exact node ID, qualified name, or display name."
        )

    def impact(
        self,
        node: str,
        direction: Literal["downstream", "upstream"] = "downstream",
        max_depth: int = 6,
        include_ambiguous: bool = True,
    ) -> GraphSubgraph:
        """BFS traversal to find the blast radius from a focus node.

        downstream: follows outgoing edges (what does this node affect?)
        upstream:   follows incoming edges (what depends on this node?)
        """
        focus = self.resolve_node(node)

        visited_nodes: set[str] = {focus.id}
        visited_edges: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(focus.id, 0)])

        while queue:
            current_id, depth = queue.popleft()
            if depth >= max_depth:
                continue

            if direction == "downstream":
                edges = self._outgoing.get(current_id, [])
            else:
                edges = self._incoming.get(current_id, [])

            for edge in edges:
                if not include_ambiguous and edge.certainty in (
                    Certainty.AMBIGUOUS,
                    Certainty.UNRESOLVED,
                ):
                    continue

                visited_edges.add(edge.id)
                neighbor_id = edge.target_id if direction == "downstream" else edge.source_id

                if neighbor_id not in visited_nodes:
                    visited_nodes.add(neighbor_id)
                    queue.append((neighbor_id, depth + 1))

        result_nodes = [
            self._nodes_by_id[nid]
            for nid in visited_nodes
            if nid != focus.id and nid in self._nodes_by_id
        ]
        result_edges = [
            self._edges_by_id[eid] for eid in visited_edges if eid in self._edges_by_id
        ]

        return GraphSubgraph(
            focus_node=focus,
            nodes=result_nodes,
            edges=result_edges,
        )

    def find_paths(
        self,
        from_node: str,
        to_node: str,
        max_depth: int = 8,
    ) -> GraphPathResult:
        """DFS enumeration of all simple paths between two nodes (capped at 20)."""
        source = self.resolve_node(from_node)
        target = self.resolve_node(to_node)

        paths: list[GraphPath] = []

        try:
            raw_paths = nx.all_simple_paths(
                self._nx_graph, source=source.id, target=target.id, cutoff=max_depth
            )
            for node_id_path in raw_paths:
                if len(paths) >= 20:
                    break
                path_nodes = [
                    self._nodes_by_id[nid]
                    for nid in node_id_path
                    if nid in self._nodes_by_id
                ]
                path_edges: list[GraphEdge] = []
                for i in range(len(node_id_path) - 1):
                    src = node_id_path[i]
                    tgt = node_id_path[i + 1]
                    edge_data = self._nx_graph.get_edge_data(src, tgt)
                    if edge_data and "edge_id" in edge_data:
                        eid = edge_data["edge_id"]
                        if eid in self._edges_by_id:
                            path_edges.append(self._edges_by_id[eid])
                paths.append(GraphPath(nodes=path_nodes, edges=path_edges))
        except nx.NetworkXError:
            pass

        return GraphPathResult(from_node=source, to_node=target, paths=paths)

    def ambiguous_audit(self) -> AmbiguousReview:
        """Collect all AMBIGUOUS and UNRESOLVED edges, sorted by type then display_name."""
        unresolved: list[GraphEdge] = []
        ambiguous: list[GraphEdge] = []

        for edge in self._document.edges:
            if edge.certainty == Certainty.UNRESOLVED:
                unresolved.append(edge)
            elif edge.certainty == Certainty.AMBIGUOUS:
                ambiguous.append(edge)

        unresolved.sort(key=lambda e: (e.type.value, e.display_name))
        ambiguous.sort(key=lambda e: (e.type.value, e.display_name))

        return AmbiguousReview(unresolved_edges=unresolved, ambiguous_edges=ambiguous)

    def dependents(self, file_path: str) -> list[GraphNode]:
        """Agent shortcut: find all nodes in a file, return the union of their upstream impact.

        Answers: "what breaks if I change this file?"
        """
        file_nodes = [
            node for node in self._document.nodes if node.file_path == file_path
        ]

        seen_ids: set[str] = set()
        result: list[GraphNode] = []

        for node in file_nodes:
            subgraph = self.impact(node.id, direction="upstream")
            for dep_node in subgraph.nodes:
                if dep_node.id not in seen_ids:
                    seen_ids.add(dep_node.id)
                    result.append(dep_node)

        return result
