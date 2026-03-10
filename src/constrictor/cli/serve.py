from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

console = Console()
err_console = Console(stderr=True)


def serve(
    graph: Path = typer.Option(
        Path("graph.json"),
        "--graph",
        "-g",
        help="Path to the graph JSON file to serve.",
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
    ),
    port: int = typer.Option(8080, "--port", "-p", help="Port to listen on."),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind to."),
) -> None:
    """Start the local web server for graph visualization.

    Loads the graph JSON and serves an interactive D3 visualization at
    http://<host>:<port>.
    """
    try:
        import uvicorn
    except ImportError:
        err_console.print(
            "[red]Error:[/red] uvicorn is required for the web server. "
            "Install it with: pip install uvicorn"
        )
        raise typer.Exit(1)

    from constrictor.export.json_export import load_json
    from constrictor.web.app import create_app

    console.print(f"[dim]Loading graph from:[/dim] {graph}")
    document = load_json(graph)
    stats = document.statistics
    console.print(
        f"[dim]  {stats.total_nodes} nodes, {stats.total_edges} edges[/dim]"
    )

    app = create_app(document)

    console.print(
        f"\n[bold green]Serving graph at[/bold green] "
        f"[bold]http://{host}:{port}[/bold]"
    )
    console.print("[dim]Press Ctrl+C to stop.[/dim]\n")

    uvicorn.run(app, host=host, port=port, log_level="warning")
