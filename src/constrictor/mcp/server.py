"""MCP server -- thin adapter layer over GraphQueryEngine.

The server is intentionally stateless with respect to graph data: it loads
graph.json on startup (or on each tool call when --auto-rescan is set). No
in-memory graph state is kept between tool calls in the stdio model, keeping
the server simple and crash-safe.

Usage:
    constrictor mcp serve [--graph graph.json] [--auto-rescan] [--transport stdio|sse] [--port 9000]
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from mcp import types
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.stdio import stdio_server

from constrictor import __version__
from constrictor.core.models import ScanOptions
from constrictor.core.orchestrator import run_scan
from constrictor.export.json_export import export_json, load_json
from constrictor.export.summary import generate_summary
from constrictor.graph.query import GraphQueryEngine, NodeNotFoundError
from constrictor.mcp.tools import get_tool_definitions

logger = logging.getLogger(__name__)

_SERVER_NAME = "constrictor"


def _load_engine(graph_path: str) -> GraphQueryEngine:
    """Load a GraphDocument from disk and return a query engine for it."""
    path = Path(graph_path)
    if not path.exists():
        raise FileNotFoundError(f"Graph file not found: {graph_path}")
    document = load_json(path)
    return GraphQueryEngine(document)


def _error_text(message: str) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=f"ERROR: {message}")]


def _json_text(data: Any) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def create_server(
    default_graph_path: str | None = None,
    auto_rescan: bool = False,
) -> Server:
    """Create and configure the Constrictor MCP server.

    Args:
        default_graph_path: Optional path to a graph.json file to use when
            callers omit the ``graph_path`` argument.
        auto_rescan: If True, re-scan the project before each tool call
            (requires ``default_graph_path`` to be a directory or for callers
            to pass ``project_path``).
    """
    server = Server(_SERVER_NAME, version=__version__)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return get_tool_definitions()

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict[str, Any]
    ) -> list[types.TextContent]:  # type: ignore[return]
        try:
            return await _dispatch(name, arguments, default_graph_path, auto_rescan)
        except FileNotFoundError as exc:
            return _error_text(str(exc))
        except NodeNotFoundError as exc:
            return _error_text(str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error in MCP tool %s", name)
            return _error_text(f"Unexpected error: {exc}")

    return server


async def _dispatch(
    name: str,
    args: dict[str, Any],
    default_graph_path: str | None,
    auto_rescan: bool,
) -> list[types.TextContent]:
    """Route tool calls to the appropriate handler."""

    if name == "constrictor_scan":
        return await _tool_scan(args)

    # All other tools need a graph file.
    graph_path = args.get("graph_path") or default_graph_path
    if not graph_path:
        return _error_text(
            "graph_path is required. Either pass it as an argument or start the "
            "server with --graph <path>."
        )

    if auto_rescan and default_graph_path:
        # Re-scan using the directory that contains the graph file.
        _do_auto_rescan(graph_path)

    if name == "constrictor_impact":
        return await _tool_impact(args, graph_path)
    if name == "constrictor_paths":
        return await _tool_paths(args, graph_path)
    if name == "constrictor_audit":
        return await _tool_audit(graph_path)
    if name == "constrictor_dependents":
        return await _tool_dependents(args, graph_path)
    if name == "constrictor_summary":
        return await _tool_summary(graph_path)

    return _error_text(f"Unknown tool: {name}")


def _do_auto_rescan(graph_path: str) -> None:
    """Re-scan and overwrite the graph file in place."""
    gp = Path(graph_path)
    project_root = gp.parent
    try:
        options = ScanOptions(root_path=project_root)
        document = run_scan(options, incremental=True)
        export_json(document, gp)
        logger.info("Auto-rescan completed: %s", graph_path)
    except Exception:  # noqa: BLE001
        logger.warning("Auto-rescan failed; using cached graph from %s", graph_path)


# ── Individual tool handlers ──────────────────────────────────────────────────

async def _tool_scan(args: dict[str, Any]) -> list[types.TextContent]:
    project_path = args.get("project_path")
    if not project_path:
        return _error_text("project_path is required for constrictor_scan.")

    root = Path(project_path)
    if not root.exists():
        return _error_text(f"project_path does not exist: {project_path}")

    output_path: str | None = args.get("output_path")
    exclude_patterns: list[str] = args.get("exclude_patterns") or []
    incremental: bool = args.get("incremental", False)

    options = ScanOptions(root_path=root, exclude_patterns=exclude_patterns)
    document = run_scan(options, incremental=incremental)

    out_path = Path(output_path) if output_path else None
    if out_path:
        export_json(document, out_path)

    stats = document.statistics
    meta = document.scan_metadata

    result: dict[str, Any] = {
        "statistics": stats.model_dump() if stats else {},
        "metadata": meta.model_dump(mode="json") if meta else {},
        "warning_count": len(document.warnings) + len(document.unresolved),
        "summary": generate_summary(document),
    }
    if output_path:
        result["graph_written_to"] = output_path

    return _json_text(result)


async def _tool_impact(args: dict[str, Any], graph_path: str) -> list[types.TextContent]:
    node = args.get("node")
    if not node:
        return _error_text("node is required for constrictor_impact.")

    direction = args.get("direction", "downstream")
    max_depth = int(args.get("max_depth", 6))
    include_ambiguous = bool(args.get("include_ambiguous", True))

    try:
        engine = _load_engine(graph_path)
        subgraph = engine.impact(
            node,
            direction=direction,  # type: ignore[arg-type]
            max_depth=max_depth,
            include_ambiguous=include_ambiguous,
        )
    except (FileNotFoundError, NodeNotFoundError) as exc:
        return _error_text(str(exc))

    result = {
        "focus_node": subgraph.focus_node.model_dump(),
        "affected_node_count": len(subgraph.nodes),
        "affected_edge_count": len(subgraph.edges),
        "nodes": [n.model_dump() for n in subgraph.nodes],
        "edges": [e.model_dump() for e in subgraph.edges],
    }
    return _json_text(result)


async def _tool_paths(args: dict[str, Any], graph_path: str) -> list[types.TextContent]:
    from_node = args.get("from_node")
    to_node = args.get("to_node")
    if not from_node or not to_node:
        return _error_text("from_node and to_node are required for constrictor_paths.")

    max_depth = int(args.get("max_depth", 8))

    try:
        engine = _load_engine(graph_path)
        path_result = engine.find_paths(from_node, to_node, max_depth=max_depth)
    except (FileNotFoundError, NodeNotFoundError) as exc:
        return _error_text(str(exc))

    result = {
        "from_node": path_result.from_node.model_dump(),
        "to_node": path_result.to_node.model_dump(),
        "path_count": len(path_result.paths),
        "paths": [
            {
                "hop_count": len(p.edges),
                "nodes": [n.model_dump() for n in p.nodes],
                "edges": [e.model_dump() for e in p.edges],
            }
            for p in path_result.paths
        ],
    }
    return _json_text(result)


async def _tool_audit(graph_path: str) -> list[types.TextContent]:
    try:
        engine = _load_engine(graph_path)
    except FileNotFoundError as exc:
        return _error_text(str(exc))
    review = engine.ambiguous_audit()

    result = {
        "unresolved_count": len(review.unresolved_edges),
        "ambiguous_count": len(review.ambiguous_edges),
        "unresolved_edges": [e.model_dump() for e in review.unresolved_edges],
        "ambiguous_edges": [e.model_dump() for e in review.ambiguous_edges],
    }
    return _json_text(result)


async def _tool_dependents(args: dict[str, Any], graph_path: str) -> list[types.TextContent]:
    file_path = args.get("file_path")
    if not file_path:
        return _error_text("file_path is required for constrictor_dependents.")

    try:
        engine = _load_engine(graph_path)
    except FileNotFoundError as exc:
        return _error_text(str(exc))
    dependent_nodes = engine.dependents(file_path)

    result = {
        "file_path": file_path,
        "dependent_count": len(dependent_nodes),
        "dependents": [n.model_dump() for n in dependent_nodes],
    }
    return _json_text(result)


async def _tool_summary(graph_path: str) -> list[types.TextContent]:
    path = Path(graph_path)
    if not path.exists():
        return _error_text(f"Graph file not found: {graph_path}")

    document = load_json(path)
    stats = document.statistics
    meta = document.scan_metadata

    result = {
        "summary": generate_summary(document),
        "statistics": stats.model_dump() if stats else {},
        "metadata": meta.model_dump(mode="json") if meta else {},
    }
    return _json_text(result)


# ── Transport runners ─────────────────────────────────────────────────────────

async def run_stdio(
    default_graph_path: str | None = None,
    auto_rescan: bool = False,
) -> None:
    """Run the MCP server on stdio (standard local agent transport)."""
    server = create_server(default_graph_path=default_graph_path, auto_rescan=auto_rescan)
    options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, options)


async def run_sse(
    host: str = "127.0.0.1",
    port: int = 9000,
    default_graph_path: str | None = None,
    auto_rescan: bool = False,
) -> None:
    """Run the MCP server over SSE (for remote/hosted use)."""
    import uvicorn
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route

    server = create_server(default_graph_path=default_graph_path, auto_rescan=auto_rescan)
    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Any) -> Any:
        async with sse.connect_sse(
            request.scope, request.receive, request._send  # type: ignore[attr-defined]
        ) as streams:
            await server.run(
                streams[0], streams[1], server.create_initialization_options()
            )

    starlette_app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )

    config = uvicorn.Config(starlette_app, host=host, port=port, log_level="info")
    uv_server = uvicorn.Server(config)
    await uv_server.serve()
