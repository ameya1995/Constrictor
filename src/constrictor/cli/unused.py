"""CLI command: constrictor unused -- find dead code candidates."""
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


def unused(
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
        help="Node types to check (default: FUNCTION, METHOD, CLASS). Repeatable.",
    ),
    exclude: Optional[list[str]] = typer.Option(
        None,
        "--exclude",
        "-e",
        help="fnmatch glob patterns for files to skip. Repeatable.",
    ),
    entry_point: Optional[list[str]] = typer.Option(
        None,
        "--entry-point",
        help="Node name patterns to treat as used (fnmatch). Repeatable.",
    ),
) -> None:
    """List functions, methods, and classes that have no incoming edges (dead code candidates).

    \b
    Examples:
      constrictor unused --graph graph.json
      constrictor unused --exclude "tests/*" --entry-point "main" --entry-point "cli_*"
      constrictor unused --type FUNCTION --type METHOD
    """
    document = load_json(graph)
    engine = GraphQueryEngine(document)

    unused_nodes = engine.find_unused(
        node_types=node_types,
        exclude_patterns=list(exclude) if exclude else None,
        entry_points=list(entry_point) if entry_point else None,
    )

    console.print()
    if not unused_nodes:
        console.print("[green]No unused nodes found.[/green]")
        console.print()
        return

    # Group by file
    by_file: dict[str, list] = {}
    for n in unused_nodes:
        by_file.setdefault(n.file_path or "<unknown>", []).append(n)

    total = len(unused_nodes)
    console.print(
        f"[bold yellow]{total}[/bold yellow] potentially unused "
        f"node{'s' if total != 1 else ''} across "
        f"[bold]{len(by_file)}[/bold] file{'s' if len(by_file) != 1 else ''}."
    )
    console.print()

    for file_path in sorted(by_file):
        nodes = by_file[file_path]
        t = Table(title=file_path, show_lines=False, show_header=True)
        t.add_column("Name", style="cyan")
        t.add_column("Type", style="yellow")
        t.add_column("Line", style="dim", justify="right")
        for n in sorted(nodes, key=lambda x: x.line_number or 0):
            t.add_row(n.display_name, n.type.value, str(n.line_number or ""))
        console.print(t)
        console.print()
