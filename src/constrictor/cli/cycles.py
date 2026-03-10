"""CLI command: constrictor cycles -- detect circular dependencies."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from constrictor.export.json_export import load_json
from constrictor.graph.query import GraphQueryEngine

console = Console()
err_console = Console(stderr=True)


def cycles(
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
    edge_types: Optional[list[str]] = typer.Option(
        None,
        "--edge-type",
        help="Edge types to include (default: IMPORTS, IMPORTS_FROM). Repeatable.",
    ),
) -> None:
    """Detect circular dependencies in the graph.

    By default checks only IMPORTS and IMPORTS_FROM edges. Results are sorted
    by cycle length (shortest first).

    \b
    Examples:
      constrictor cycles --graph graph.json
      constrictor cycles --edge-type CALLS
    """
    document = load_json(graph)
    engine = GraphQueryEngine(document)

    found = engine.find_cycles(edge_types=list(edge_types) if edge_types else None)

    console.print()
    if not found:
        console.print("[green]No circular dependencies detected.[/green]")
        console.print()
        return

    console.print(
        f"[bold red]{len(found)}[/bold red] circular "
        f"{'dependency' if len(found) == 1 else 'dependencies'} detected.\n"
    )

    for i, cycle in enumerate(found, start=1):
        length = cycle["length"]
        nodes = cycle["nodes"]
        node_names = " → ".join(n["qualified_name"] for n in nodes)
        console.print(
            f"  [bold]Cycle {i}[/bold] [dim]({length} node{'s' if length != 1 else ''})[/dim]"
        )
        console.print(f"    {node_names}")
        files = sorted({n["file_path"] for n in nodes if n["file_path"]})
        for fp in files:
            console.print(f"    [dim]{fp}[/dim]")
        console.print()
