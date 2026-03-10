from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

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
) -> None:
    """Find all paths between two nodes in the dependency graph."""
    document = load_json(graph)
    engine = GraphQueryEngine(document)

    try:
        result = engine.find_paths(from_node, to_node, max_depth=depth)
    except NodeNotFoundError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)

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
