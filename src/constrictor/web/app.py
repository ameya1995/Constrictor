from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from constrictor.graph.models import (
    EdgeType,
    GraphDocument,
    GraphEdge,
    GraphNode,
    GraphPathResult,
    GraphSubgraph,
    NodeType,
)
from constrictor.graph.query import GraphQueryEngine, NodeNotFoundError

_STATIC_DIR = Path(__file__).parent / "static"


def create_app(document: GraphDocument) -> FastAPI:
    """Create and return the FastAPI application serving a loaded GraphDocument."""

    app = FastAPI(
        title="Constrictor Graph Explorer",
        description="Browse and query the dependency graph.",
        version="0.1.0",
    )

    engine = GraphQueryEngine(document)

    # ------------------------------------------------------------------
    # API routes
    # ------------------------------------------------------------------

    @app.get("/api/summary")
    def api_summary() -> dict:
        """Return scan statistics and metadata."""
        stats = document.statistics.model_dump()
        meta = document.scan_metadata.model_dump() if document.scan_metadata else None
        return {"statistics": stats, "scan_metadata": meta}

    @app.get("/api/nodes", response_model=list[GraphNode])
    def api_nodes(
        type: Optional[list[NodeType]] = Query(default=None),
    ) -> list[GraphNode]:
        """Return all nodes, optionally filtered by one or more types."""
        nodes = document.nodes
        if type:
            nodes = [n for n in nodes if n.type in type]
        return nodes

    @app.get("/api/edges", response_model=list[GraphEdge])
    def api_edges(
        type: Optional[list[EdgeType]] = Query(default=None),
    ) -> list[GraphEdge]:
        """Return all edges, optionally filtered by one or more types."""
        edges = document.edges
        if type:
            edges = [e for e in edges if e.type in type]
        return edges

    @app.get("/api/impact", response_model=GraphSubgraph)
    def api_impact(
        node: str = Query(..., description="Node ID or name to analyze."),
        direction: str = Query(
            "downstream",
            description="Direction: 'downstream' or 'upstream'.",
        ),
        depth: int = Query(6, ge=1, le=20, description="Maximum traversal depth."),
    ) -> GraphSubgraph:
        """Return the impact subgraph from a given node."""
        if direction not in ("downstream", "upstream"):
            raise HTTPException(
                status_code=400,
                detail="direction must be 'downstream' or 'upstream'",
            )
        try:
            return engine.impact(node, direction=direction, max_depth=depth)  # type: ignore[arg-type]
        except NodeNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.get("/api/paths", response_model=GraphPathResult)
    def api_paths(
        from_: str = Query(..., alias="from", description="Source node ID or name."),
        to: str = Query(..., description="Target node ID or name."),
        depth: int = Query(8, ge=1, le=20, description="Maximum path depth."),
    ) -> GraphPathResult:
        """Return all simple paths between two nodes (up to 20)."""
        try:
            return engine.find_paths(from_, to, max_depth=depth)
        except NodeNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.get("/api/services", response_model=list[GraphNode])
    def api_services() -> list[GraphNode]:
        """Return all SERVICE and COMPONENT nodes with their API contract surfaces."""
        return [
            n for n in document.nodes
            if n.type in (NodeType.SERVICE, NodeType.COMPONENT)
        ]

    @app.get("/api/audit")
    def api_audit() -> dict:
        """Return AMBIGUOUS and UNRESOLVED edges enriched with source/target display names."""
        review = engine.ambiguous_audit()
        node_index = {n.id: n for n in document.nodes}

        def enrich(e: GraphEdge) -> dict:
            d = e.model_dump(mode="json")
            src = node_index.get(e.source_id)
            tgt = node_index.get(e.target_id)
            d["source_name"] = src.display_name if src else e.source_id
            d["source_file"] = src.file_path if src else None
            d["target_name"] = tgt.display_name if tgt else e.target_id
            d["target_file"] = tgt.file_path if tgt else None
            return d

        return {
            "unresolved_count": len(review.unresolved_edges),
            "ambiguous_count": len(review.ambiguous_edges),
            "edges": [enrich(e) for e in review.unresolved_edges + review.ambiguous_edges],
        }

    # ------------------------------------------------------------------
    # Static / UI
    # ------------------------------------------------------------------

    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

        @app.get("/", response_class=HTMLResponse, response_model=None)
        def root() -> HTMLResponse | FileResponse:
            index = _STATIC_DIR / "index.html"
            if index.exists():
                return FileResponse(str(index))
            return HTMLResponse("<h1>Constrictor</h1><p>Static files not found.</p>")
    else:
        @app.get("/", response_class=HTMLResponse)
        def root_fallback() -> HTMLResponse:
            return HTMLResponse(
                "<h1>Constrictor Graph Explorer</h1>"
                "<p>Static UI not available. Use the <a href='/docs'>/docs</a> API.</p>"
            )

    return app
