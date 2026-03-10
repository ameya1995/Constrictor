"""CLI command: constrictor search -- search for nodes in the dependency graph."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from constrictor.export.json_export import load_json
from constrictor.graph.query import GraphQueryEngine

console = Console()
err_console = Console(stderr=True)


def search(
    query: str = typer.Argument(
        ...,
        help="Search string: partial name, qualified name fragment, or regex.",
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
    node_types: Optional[list[str]] = typer.Option(
        None,
        "--type",
        "-t",
        help="Restrict to these node types (e.g. FUNCTION, CLASS). Repeatable.",
    ),
    file_pattern: Optional[str] = typer.Option(
        None,
        "--file",
        "-f",
        help="fnmatch glob to filter by file path, e.g. 'app/routes/*'.",
    ),
    limit: int = typer.Option(
        10,
        "--limit",
        "-l",
        help="Maximum number of results.",
    ),
) -> None:
    """Search the dependency graph for nodes matching a name or pattern.

    Results are ranked by match quality: exact > prefix > substring > regex.
    """
    document = load_json(graph)
    engine = GraphQueryEngine(document)

    nodes = engine.search(
        query,
        node_types=node_types,
        file_pattern=file_pattern,
        limit=limit,
    )

    console.print()
    if not nodes:
        console.print(f"[dim]No nodes found matching {query!r}.[/dim]")
        console.print()
        return

    table = Table(
        title=f"Search results for [bold cyan]{query}[/bold cyan]",
        show_lines=False,
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Qualified Name", style="cyan")
    table.add_column("Type", style="yellow")
    table.add_column("Location", style="dim")

    for i, node in enumerate(nodes, start=1):
        loc = node.file_path or ""
        if node.line_number is not None:
            loc = f"{loc}:{node.line_number}"
        table.add_row(str(i), node.qualified_name, node.type.value, loc)

    console.print(table)
    console.print(
        f"\n[dim]{len(nodes)} result{'s' if len(nodes) != 1 else ''} "
        f"(node id available via --verbose or MCP)[/dim]"
    )
    console.print()
