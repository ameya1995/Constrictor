from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from constrictor.export.format_output import validate_format
from constrictor.export.json_export import load_json
from constrictor.graph.query import GraphQueryEngine, NodeNotFoundError

console = Console()
err_console = Console(stderr=True)


def paths(
    from_node: str = typer.Option(
        ...,
        "--from",
        "-f",
        help="Source node ID, qualified name, or display name.",
    ),
    to_node: str = typer.Option(
        ...,
        "--to",
        "-t",
        help="Target node ID, qualified name, or display name.",
    ),
    graph: Path = typer.Option(
        Path("graph.json"),
        "--graph",
        "-g",
        help="Path to the graph JSON file.",
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
    ),
    depth: int = typer.Option(
        8,
        "--depth",
        help="Maximum path length (hops).",
    ),
    fmt: str = typer.Option(
        "full",
        "--format",
        help="Output format: 'full' (default), 'compact' (token-efficient), or 'files' (file paths only).",
    ),
    edge_types: Optional[list[str]] = typer.Option(
        None,
        "--edge-type",
        help="Only traverse edges of these types. Repeatable.",
    ),
    node_types: Optional[list[str]] = typer.Option(
        None,
        "--node-type",
        help="Only yield paths through intermediate nodes of these types. Repeatable.",
    ),
) -> None:
    """Find all paths between two nodes in the dependency graph."""
    try:
        validate_format(fmt)
    except ValueError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=2)

    document = load_json(graph)
    engine = GraphQueryEngine(document)

    try:
        result = engine.find_paths(
            from_node,
            to_node,
            max_depth=depth,
            edge_types=list(edge_types) if edge_types else None,
            node_types=list(node_types) if node_types else None,
        )
    except NodeNotFoundError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)

    if fmt == "files":
        all_nodes = [result.from_node, result.to_node]
        for p in result.paths:
            all_nodes.extend(p.nodes)
        files = sorted({n.file_path for n in all_nodes if n.file_path})
        console.print(json.dumps(files, indent=2))
        return

    if fmt == "compact":
        compact_paths = []
        for p in result.paths:
            compact_paths.append(
                {
                    "hop_count": len(p.edges),
                    "nodes": [n.qualified_name for n in p.nodes],
                    "edge_types": [e.type.value for e in p.edges],
                }
            )
        console.print(
            json.dumps(
                {
                    "from": result.from_node.qualified_name,
                    "to": result.to_node.qualified_name,
                    "path_count": len(result.paths),
                    "paths": compact_paths,
                },
                indent=2,
            )
        )
        return

    console.print()
    console.print(
        f"[bold]Paths from[/bold] [cyan]{result.from_node.display_name}[/cyan] "
        f"[bold]to[/bold] [cyan]{result.to_node.display_name}[/cyan]:"
    )

    if not result.paths:
        console.print("  [dim]No paths found.[/dim]")
        console.print()
        return

    for i, path in enumerate(result.paths, start=1):
        hop_count = len(path.edges)
        console.print()
        console.print(
            f"  [bold]Path {i}[/bold] [dim]({hop_count} hop{'s' if hop_count != 1 else ''})[/dim]"
        )
        if not path.nodes:
            continue

        node_iter = iter(path.nodes)
        first_node = next(node_iter)
        console.print(f"    [cyan]{first_node.display_name}[/cyan] [dim]({first_node.type.value})[/dim]")

        for edge, node in zip(path.edges, node_iter):
            console.print(f"      [dim]--\\[{edge.type.value}]-->[/dim]")
            console.print(f"    [green]{node.display_name}[/green] [dim]({node.type.value})[/dim]")

    console.print()
    total = len(result.paths)
    console.print(
        f"[bold]{total}[/bold] path{'s' if total != 1 else ''} found "
        f"[dim](capped at 20)[/dim]."
        if total == 20
        else f"[bold]{total}[/bold] path{'s' if total != 1 else ''} found."
    )
    console.print()
