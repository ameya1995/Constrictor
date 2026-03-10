from __future__ import annotations

import fnmatch
import re
from collections import deque
from typing import Any, Literal

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
        edge_types: list[str] | None = None,
        node_types: list[str] | None = None,
        file_pattern: str | None = None,
    ) -> GraphSubgraph:
        """BFS traversal to find the blast radius from a focus node.

        downstream: follows outgoing edges (what does this node affect?)
        upstream:   follows incoming edges (what depends on this node?)

        Optional filters (applied during traversal, not post-hoc):
          edge_types   -- only traverse edges of these types (e.g. ["CALLS"])
          node_types   -- only include result nodes of these types
          file_pattern -- only include result nodes whose file_path matches this glob
        """
        focus = self.resolve_node(node)

        allowed_edge_types: set[str] | None = {t.upper() for t in edge_types} if edge_types else None
        allowed_node_types: set[str] | None = {t.upper() for t in node_types} if node_types else None

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

                if allowed_edge_types and edge.type.value not in allowed_edge_types:
                    continue

                visited_edges.add(edge.id)
                neighbor_id = edge.target_id if direction == "downstream" else edge.source_id

                if neighbor_id not in visited_nodes:
                    visited_nodes.add(neighbor_id)
                    queue.append((neighbor_id, depth + 1))

        result_nodes = []
        for nid in visited_nodes:
            if nid == focus.id or nid not in self._nodes_by_id:
                continue
            n = self._nodes_by_id[nid]
            if allowed_node_types and n.type.value not in allowed_node_types:
                continue
            if file_pattern and n.file_path:
                if not fnmatch.fnmatch(n.file_path, file_pattern):
                    continue
            result_nodes.append(n)

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
        edge_types: list[str] | None = None,
        node_types: list[str] | None = None,
    ) -> GraphPathResult:
        """DFS enumeration of all simple paths between two nodes (capped at 20).

        Optional filters:
          edge_types -- only traverse edges of these types
          node_types -- only yield paths whose intermediate nodes match these types
        """
        source = self.resolve_node(from_node)
        target = self.resolve_node(to_node)

        allowed_edge_types: set[str] | None = {t.upper() for t in edge_types} if edge_types else None
        allowed_node_types: set[str] | None = {t.upper() for t in node_types} if node_types else None

        # Build a filtered subgraph view for path finding
        if allowed_edge_types:
            filtered = nx.DiGraph()
            for edge in self._document.edges:
                if edge.type.value in allowed_edge_types:
                    filtered.add_edge(edge.source_id, edge.target_id, edge_id=edge.id)
            nx_graph = filtered
        else:
            nx_graph = self._nx_graph

        paths: list[GraphPath] = []

        try:
            raw_paths = nx.all_simple_paths(
                nx_graph, source=source.id, target=target.id, cutoff=max_depth
            )
            for node_id_path in raw_paths:
                if len(paths) >= 20:
                    break

                # Apply node type filter on intermediate nodes
                if allowed_node_types:
                    skip = False
                    for nid in node_id_path[1:-1]:  # exclude source/target from filter
                        n = self._nodes_by_id.get(nid)
                        if n and n.type.value not in allowed_node_types:
                            skip = True
                            break
                    if skip:
                        continue

                path_nodes = [
                    self._nodes_by_id[nid]
                    for nid in node_id_path
                    if nid in self._nodes_by_id
                ]
                path_edges: list[GraphEdge] = []
                for i in range(len(node_id_path) - 1):
                    src = node_id_path[i]
                    tgt = node_id_path[i + 1]
                    edge_data = nx_graph.get_edge_data(src, tgt)
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

    def search(
        self,
        query: str,
        node_types: list[str] | None = None,
        file_pattern: str | None = None,
        limit: int = 10,
    ) -> list[GraphNode]:
        """Search for nodes by name/qualified name, returning ranked results.

        Scoring (higher is better):
          4 -- exact qualified_name or display_name match (case-insensitive)
          3 -- qualified_name or display_name starts with query
          2 -- query is a substring of qualified_name
          1 -- query is a substring of display_name
          0 -- regex match anywhere in qualified_name

        Filters applied after scoring:
          node_types   -- restrict to these NodeType values (e.g. ["FUNCTION", "CLASS"])
          file_pattern -- fnmatch glob against file_path (e.g. "app/routes/*")
        """
        lower = query.lower()

        # Pre-compile regex lazily; fall back gracefully if invalid
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error:
            pattern = None

        # Build allowed type set
        allowed_types: set[str] | None = None
        if node_types:
            allowed_types = {t.upper() for t in node_types}

        scored: list[tuple[int, GraphNode]] = []
        for node in self._document.nodes:
            # Type filter
            if allowed_types and node.type.value not in allowed_types:
                continue

            # File pattern filter
            if file_pattern and node.file_path:
                if not fnmatch.fnmatch(node.file_path, file_pattern):
                    continue
            elif file_pattern and not node.file_path:
                continue

            qn = node.qualified_name.lower()
            dn = node.display_name.lower()

            if qn == lower or dn == lower:
                score = 4
            elif qn.startswith(lower) or dn.startswith(lower):
                score = 3
            elif lower in qn:
                score = 2
            elif lower in dn:
                score = 1
            elif pattern and (pattern.search(node.qualified_name) or pattern.search(node.display_name)):
                score = 0
            else:
                continue

            scored.append((score, node))

        scored.sort(key=lambda x: (-x[0], x[1].qualified_name))
        return [node for _, node in scored[:limit]]

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

    def file_context(self, file_path: str) -> dict:
        """Return a structured summary of all graph entities in a given file.

        Groups nodes by type (classes, functions, endpoints, models) and lists
        imports (outgoing IMPORTS/IMPORTS_FROM edges) and importers (files that
        import this file).
        """
        from constrictor.graph.models import EdgeType

        file_nodes = [n for n in self._document.nodes if n.file_path == file_path]
        node_ids = {n.id for n in file_nodes}

        # Outgoing import edges from nodes in this file
        imports_out: list[str] = []
        # Incoming edges from *other* files -- the "imported_by" set
        imported_by_files: set[str] = set()

        for edge in self._document.edges:
            if edge.type in (EdgeType.IMPORTS, EdgeType.IMPORTS_FROM):
                if edge.source_id in node_ids:
                    # resolve target display name if possible
                    tgt = self._nodes_by_id.get(edge.target_id)
                    imports_out.append(tgt.qualified_name if tgt else edge.display_name)
                elif edge.target_id in node_ids:
                    src = self._nodes_by_id.get(edge.source_id)
                    if src and src.file_path and src.file_path != file_path:
                        imported_by_files.add(src.file_path)

        classes = []
        functions = []
        methods = []
        endpoints = []
        models = []
        other = []

        for node in sorted(file_nodes, key=lambda n: n.line_number or 0):
            nt = node.type.value
            entry: dict[str, Any] = {
                "name": node.display_name,
                "qualified_name": node.qualified_name,
                "line": node.line_number,
            }

            # Enrich classes with base info from INHERITS edges
            if nt == "CLASS":
                bases = []
                for edge in self._outgoing.get(node.id, []):
                    if edge.type == EdgeType.INHERITS:
                        tgt = self._nodes_by_id.get(edge.target_id)
                        bases.append(tgt.display_name if tgt else edge.display_name)
                entry["bases"] = bases
                classes.append(entry)
            elif nt == "FUNCTION":
                # List direct callees
                callees = [
                    (
                        self._nodes_by_id[e.target_id].display_name
                        if e.target_id in self._nodes_by_id
                        else e.display_name
                    )
                    for e in self._outgoing.get(node.id, [])
                    if e.type == EdgeType.CALLS
                ]
                entry["calls"] = callees
                functions.append(entry)
            elif nt == "METHOD":
                methods.append(entry)
            elif nt == "ENDPOINT":
                meta = node.metadata or {}
                entry["http_method"] = meta.get("http_method", "")
                entry["path"] = meta.get("path", node.display_name)
                endpoints.append(entry)
            elif nt in ("SQLALCHEMY_MODEL", "TABLE"):
                models.append(entry)
            else:
                other.append(entry)

        return {
            "file": file_path,
            "node_count": len(file_nodes),
            "modules_imported": sorted(set(imports_out)),
            "imported_by": sorted(imported_by_files),
            "classes": classes,
            "functions": functions,
            "methods": methods,
            "endpoints": endpoints,
            "models": models,
            "other": other,
        }

    def diff_impact(
        self,
        regions: list,
        fmt: str = "compact",
    ) -> dict:
        """Return the blast radius for a set of changed code regions (file+line ranges).

        *regions* is a list of ``ChangedRegion`` objects from ``analysis.diff``.

        Output groups nodes into three tiers:
          directly_changed -- nodes whose definition falls within a changed line range
          immediate         -- nodes one hop away from changed nodes
          transitive        -- all further reachable nodes
        """
        from constrictor.export.format_output import format_nodes

        # Build path -> nodes index for fast lookup
        path_to_nodes: dict[str, list[GraphNode]] = {}
        for node in self._document.nodes:
            if node.file_path:
                path_to_nodes.setdefault(node.file_path, []).append(node)

        directly_changed: list[GraphNode] = []
        seen: set[str] = set()

        for region in regions:
            fp = region.file_path
            line_start = region.line_start
            line_end = region.line_end

            # Try exact path first; fall back to suffix match
            candidates = path_to_nodes.get(fp, [])
            if not candidates:
                for stored_path, stored_nodes in path_to_nodes.items():
                    if stored_path.endswith(fp) or fp.endswith(stored_path):
                        candidates = stored_nodes
                        break

            for node in candidates:
                if node.id in seen:
                    continue
                ln = node.line_number
                if ln is None or (line_start <= ln <= line_end):
                    directly_changed.append(node)
                    seen.add(node.id)

        # One-hop neighbours
        immediate: list[GraphNode] = []
        immediate_ids: set[str] = set()
        for node in directly_changed:
            for edge in self._outgoing.get(node.id, []) + self._incoming.get(node.id, []):
                nbr_id = edge.target_id if edge.source_id == node.id else edge.source_id
                if nbr_id not in seen:
                    nbr = self._nodes_by_id.get(nbr_id)
                    if nbr:
                        immediate.append(nbr)
                        immediate_ids.add(nbr_id)
                        seen.add(nbr_id)

        # Full transitive blast radius from all directly changed nodes
        transitive: list[GraphNode] = []
        all_focus_ids = {n.id for n in directly_changed}
        queue = deque(list(all_focus_ids))
        visited_full: set[str] = set(all_focus_ids)
        visited_full.update(immediate_ids)
        for node in directly_changed:
            queue.append(node.id)

        while queue:
            current_id = queue.popleft()
            for edge in self._outgoing.get(current_id, []):
                nbr_id = edge.target_id
                if nbr_id not in visited_full:
                    visited_full.add(nbr_id)
                    nbr = self._nodes_by_id.get(nbr_id)
                    if nbr and nbr.id not in {n.id for n in directly_changed} and nbr.id not in immediate_ids:
                        transitive.append(nbr)
                    queue.append(nbr_id)

        def _fmt(nodes: list[GraphNode]) -> list:
            return format_nodes(nodes, fmt=fmt)  # type: ignore[arg-type]

        return {
            "changed_region_count": len(regions),
            "directly_changed": _fmt(directly_changed),
            "directly_changed_count": len(directly_changed),
            "immediate_dependents": _fmt(immediate),
            "immediate_count": len(immediate),
            "transitive_dependents": _fmt(transitive),
            "transitive_count": len(transitive),
        }

    def find_unused(
        self,
        node_types: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        entry_points: list[str] | None = None,
    ) -> list[GraphNode]:
        """Find nodes that have no incoming edges (potential dead code).

        Nodes are filtered by ``node_types`` (default: FUNCTION, METHOD, CLASS).
        Nodes in files matching any ``exclude_patterns`` glob are skipped.
        Nodes whose qualified_name or display_name matches any ``entry_points``
        pattern are considered "used" and excluded from the result.
        """
        default_types = {"FUNCTION", "METHOD", "CLASS"}
        if node_types:
            target_types = {t.upper() for t in node_types}
        else:
            target_types = default_types

        # Build set of node IDs that have at least one incoming edge
        has_incoming: set[str] = {edge.target_id for edge in self._document.edges}

        result: list[GraphNode] = []
        for node in self._document.nodes:
            if node.type.value not in target_types:
                continue
            if node.id in has_incoming:
                continue

            # File exclusion
            if exclude_patterns and node.file_path:
                if any(fnmatch.fnmatch(node.file_path, pat) for pat in exclude_patterns):
                    continue

            # Entry point whitelist
            if entry_points:
                if any(
                    fnmatch.fnmatch(node.qualified_name, ep) or fnmatch.fnmatch(node.display_name, ep)
                    for ep in entry_points
                ):
                    continue

            result.append(node)

        return sorted(result, key=lambda n: (n.file_path or "", n.line_number or 0))

    def batch_impact(
        self,
        nodes: list[str],
        direction: Literal["downstream", "upstream"] = "downstream",
        max_depth: int = 6,
        include_ambiguous: bool = True,
    ) -> dict:
        """Run impact analysis on multiple nodes and return the merged, deduplicated result."""
        seen_node_ids: set[str] = set()
        seen_edge_ids: set[str] = set()
        all_nodes: list[GraphNode] = []
        all_edges: list[GraphEdge] = []
        focus_names: list[str] = []

        for node_id in nodes:
            try:
                subgraph = self.impact(
                    node_id,
                    direction=direction,
                    max_depth=max_depth,
                    include_ambiguous=include_ambiguous,
                )
            except NodeNotFoundError:
                focus_names.append(f"<not found: {node_id}>")
                continue

            focus_names.append(subgraph.focus_node.qualified_name)

            for n in subgraph.nodes:
                if n.id not in seen_node_ids:
                    seen_node_ids.add(n.id)
                    all_nodes.append(n)

            for e in subgraph.edges:
                if e.id not in seen_edge_ids:
                    seen_edge_ids.add(e.id)
                    all_edges.append(e)

        return {
            "focus_nodes": focus_names,
            "nodes": all_nodes,
            "edges": all_edges,
        }

    def find_cycles(self, edge_types: list[str] | None = None) -> list[dict]:
        """Find circular dependencies in the graph using NetworkX simple_cycles.

        By default restricts to IMPORTS and IMPORTS_FROM edges. Pass
        ``edge_types`` to analyse a different set.
        """
        from constrictor.graph.models import EdgeType as ET

        if edge_types:
            allowed = {t.upper() for t in edge_types}
        else:
            allowed = {ET.IMPORTS.value, ET.IMPORTS_FROM.value}

        subgraph = nx.DiGraph()
        for edge in self._document.edges:
            if edge.type.value in allowed:
                subgraph.add_edge(edge.source_id, edge.target_id)

        cycles: list[dict] = []
        for raw_cycle in nx.simple_cycles(subgraph):
            nodes = [
                {
                    "qualified_name": self._nodes_by_id[nid].qualified_name if nid in self._nodes_by_id else nid,
                    "file_path": self._nodes_by_id[nid].file_path if nid in self._nodes_by_id else None,
                }
                for nid in raw_cycle
            ]
            cycles.append({"length": len(raw_cycle), "nodes": nodes})

        cycles.sort(key=lambda c: c["length"])
        return cycles
