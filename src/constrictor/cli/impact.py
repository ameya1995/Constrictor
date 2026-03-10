from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.tree import Tree

from constrictor.export.json_export import load_json
from constrictor.graph.query import GraphQueryEngine, NodeNotFoundError

console = Console()
err_console = Console(stderr=True)


def impact(
    node: str = typer.Option(
        ...,
        "--node",
        "-n",
        help="Node ID, qualified name, or display name to analyze.",
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
    direction: str = typer.Option(
        "downstream",
        "--direction",
        "-d",
        help="Traversal direction: 'downstream' (what this affects) or 'upstream' (what depends on this).",
    ),
    depth: int = typer.Option(
        6,
        "--depth",
        help="Maximum traversal depth.",
    ),
    no_ambiguous: bool = typer.Option(
        False,
        "--no-ambiguous",
        help="Exclude AMBIGUOUS and UNRESOLVED edges from traversal.",
    ),
) -> None:
    """Show the blast radius of a node -- what it affects or what depends on it."""
    if direction not in ("downstream", "upstream"):
        err_console.print(
            "[red]Error:[/red] --direction must be 'downstream' or 'upstream'."
        )
        raise typer.Exit(code=2)

    document = load_json(graph)
    engine = GraphQueryEngine(document)

    try:
        subgraph = engine.impact(
            node,
            direction=direction,  # type: ignore[arg-type]
            max_depth=depth,
            include_ambiguous=not no_ambiguous,
        )
    except NodeNotFoundError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)

    focus = subgraph.focus_node
    affected_nodes = subgraph.nodes
    affected_edges = subgraph.edges

    dir_label = "downstream" if direction == "downstream" else "upstream"
    title = (
        f"[bold]Impact of[/bold] [cyan]{focus.display_name}[/cyan] "
        f"([dim]{dir_label}, depth={depth}[/dim]):"
    )
    console.print()
    console.print(title)

    if not affected_nodes:
        console.print("  [dim]No affected nodes found.[/dim]")
        console.print()
        return

    edges_by_target = {e.target_id: e for e in affected_edges} if direction == "downstream" else {}
    edges_by_source = {e.source_id: e for e in affected_edges} if direction == "upstream" else {}

    edge_lookup = edges_by_target if direction == "downstream" else edges_by_source

    tree = Tree(f"[bold cyan]{focus.display_name}[/bold cyan] [dim]({focus.type.value})[/dim]")

    files_affected: set[str] = set()
    for n in affected_nodes:
        if n.file_path:
            files_affected.add(n.file_path)
        edge = edge_lookup.get(n.id if direction == "downstream" else n.id)
        edge_label = f" [dim]\\[{edge.type.value}][/dim]" if edge else ""
        tree.add(
            f"[green]{n.display_name}[/green] [dim]({n.type.value})[/dim]{edge_label}"
        )

    console.print(tree)
    console.print()
    console.print(
        f"[bold]{len(affected_nodes)}[/bold] node{'s' if len(affected_nodes) != 1 else ''} affected "
        f"across [bold]{len(files_affected)}[/bold] file{'s' if len(files_affected) != 1 else ''}."
    )
    console.print()
