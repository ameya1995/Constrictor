"""CLI command: constrictor context -- show all graph entities in a file."""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from constrictor.export.json_export import load_json
from constrictor.graph.query import GraphQueryEngine

console = Console()
err_console = Console(stderr=True)


def context(
    file_path: str = typer.Argument(
        ...,
        help="Path to the file to inspect (as stored in the graph).",
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
) -> None:
    """Show all graph entities defined in a file: classes, functions, endpoints, models, imports."""
    document = load_json(graph)
    engine = GraphQueryEngine(document)

    ctx = engine.file_context(file_path)

    console.print()
    console.print(Panel(f"[bold cyan]{ctx['file']}[/bold cyan]  [dim]({ctx['node_count']} nodes)[/dim]"))

    if ctx["modules_imported"]:
        console.print("[bold]Imports:[/bold]")
        for imp in ctx["modules_imported"]:
            console.print(f"  [dim]→[/dim] {imp}")
        console.print()

    if ctx["imported_by"]:
        console.print("[bold]Imported by:[/bold]")
        for fp in ctx["imported_by"]:
            console.print(f"  [dim]←[/dim] {fp}")
        console.print()

    def _table(title: str, rows: list[dict], cols: list[tuple[str, str]]) -> None:
        if not rows:
            return
        t = Table(title=title, show_lines=False)
        for col_name, col_style in cols:
            t.add_column(col_name, style=col_style)
        for row in rows:
            t.add_row(*[str(row.get(c, "") or "") for c, _ in cols])
        console.print(t)
        console.print()

    _table(
        "Classes",
        ctx["classes"],
        [("name", "cyan"), ("bases", "dim"), ("line", "dim")],
    )
    _table(
        "Functions",
        ctx["functions"],
        [("name", "green"), ("calls", "dim"), ("line", "dim")],
    )
    _table(
        "Methods",
        ctx["methods"],
        [("name", "green"), ("line", "dim")],
    )
    _table(
        "Endpoints",
        ctx["endpoints"],
        [("http_method", "yellow"), ("path", "cyan"), ("name", "dim"), ("line", "dim")],
    )
    _table(
        "Models",
        ctx["models"],
        [("name", "magenta"), ("line", "dim")],
    )

    if ctx["other"]:
        _table(
            "Other",
            ctx["other"],
            [("name", "white"), ("qualified_name", "dim"), ("line", "dim")],
        )

    if ctx["node_count"] == 0:
        console.print(f"[dim]No graph nodes found for {file_path!r}.[/dim]")
        console.print(
            "[dim]Tip: check that the path matches what's stored in the graph "
            "(use constrictor search to browse).[/dim]"
        )

    console.print()
