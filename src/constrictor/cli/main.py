from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from constrictor import __version__
from constrictor.cli.impact import impact
from constrictor.cli.paths import paths
from constrictor.cli.serve import serve
from constrictor.cli.watch import watch
from constrictor.core.ignore import load_ignore_patterns
from constrictor.core.models import ScanOptions
from constrictor.core.orchestrator import run_scan
from constrictor.export.json_export import export_json, load_json
from constrictor.export.summary import generate_summary
from constrictor.graph.query import GraphQueryEngine, NodeNotFoundError

app = typer.Typer(
    name="constrictor",
    help="Static dependency and blast-radius analyzer for Python codebases.",
    add_completion=False,
    no_args_is_help=True,
)

app.command("impact")(impact)
app.command("paths")(paths)
app.command("watch")(watch)
app.command("serve")(serve)

# ── Export sub-app ────────────────────────────────────────────────────────
export_app = typer.Typer(
    name="export",
    help="Export the dependency graph to various formats.",
    no_args_is_help=True,
)
app.add_typer(export_app, name="export")

# ── Agent sub-app ─────────────────────────────────────────────────────────
agent_app = typer.Typer(
    name="agent",
    help="Agent integration utilities.",
    no_args_is_help=True,
)
app.add_typer(agent_app, name="agent")

# ── MCP sub-app ───────────────────────────────────────────────────────────
mcp_app = typer.Typer(
    name="mcp",
    help="Model Context Protocol server for AI agent integration.",
    no_args_is_help=True,
)
app.add_typer(mcp_app, name="mcp")

console = Console()
err_console = Console(stderr=True)


# ── Export sub-commands ───────────────────────────────────────────────────

@export_app.command("neo4j")
def export_neo4j_cmd(
    path: Path = typer.Argument(
        ...,
        help="Path to the Python project root to scan.",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    output_dir: Path = typer.Option(
        ...,
        "--output",
        "-o",
        help="Directory to write nodes.csv and edges.csv.",
    ),
    exclude: Optional[list[str]] = typer.Option(
        None,
        "--exclude",
        "-e",
        help="Additional glob patterns to exclude.",
    ),
) -> None:
    """Scan a project and export the graph as Neo4j bulk-import CSV files."""
    from constrictor.export.neo4j_export import export_neo4j

    options = ScanOptions(
        root_path=path,
        exclude_patterns=list(exclude) if exclude else [],
    )
    document = run_scan(options)
    export_neo4j(document, output_dir)
    console.print(f"[bold]Neo4j CSV written to:[/bold] {output_dir}")
    console.print(f"[dim]  nodes.csv, edges.csv[/dim]")


@export_app.command("json")
def export_json_cmd(
    path: Path = typer.Argument(
        ...,
        help="Path to the Python project root to scan.",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    output: Path = typer.Option(
        ...,
        "--output",
        "-o",
        help="Output file path for the graph JSON.",
    ),
    exclude: Optional[list[str]] = typer.Option(
        None,
        "--exclude",
        "-e",
        help="Additional glob patterns to exclude.",
    ),
) -> None:
    """Scan a project and export the graph as JSON (alias for `scan -o`)."""
    options = ScanOptions(
        root_path=path,
        exclude_patterns=list(exclude) if exclude else [],
    )
    document = run_scan(options)
    export_json(document, output)
    console.print(f"[bold]Graph JSON written to:[/bold] {output}")
    stats = document.statistics
    console.print(f"[dim]  {stats.total_nodes} nodes, {stats.total_edges} edges[/dim]")


# ── Agent sub-commands ────────────────────────────────────────────────────

@agent_app.command("skill")
def agent_skill(
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Write SKILL.md to this path. Prints to stdout if omitted.",
    ),
) -> None:
    """Generate a SKILL.md file for agent runtime discovery.

    The generated file instructs AI agents (Codex, Claude Code, Copilot, etc.)
    how to install and use Constrictor.
    """
    from constrictor.agent.skill import generate_skill_md

    rendered = generate_skill_md(output_path=output)

    if output:
        console.print(f"[bold]SKILL.md written to:[/bold] {output}")
    else:
        console.print(rendered)


# ── MCP sub-commands ──────────────────────────────────────────────────────

@mcp_app.command("serve")
def mcp_serve(
    graph: Optional[Path] = typer.Option(
        None,
        "--graph",
        "-g",
        help=(
            "Path to a pre-built graph.json file. "
            "When omitted, callers must pass graph_path in each tool call."
        ),
    ),
    auto_rescan: bool = typer.Option(
        False,
        "--auto-rescan",
        help=(
            "Re-scan the project and refresh graph.json before each tool call. "
            "Uses incremental scanning when a cache is available."
        ),
    ),
    transport: str = typer.Option(
        "stdio",
        "--transport",
        "-t",
        help="Transport to use: stdio (default) or sse.",
    ),
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        help="Host to bind when using SSE transport.",
    ),
    port: int = typer.Option(
        9000,
        "--port",
        "-p",
        help="Port to listen on when using SSE transport.",
    ),
) -> None:
    """Start the Constrictor MCP server.

    Exposes Constrictor's graph query capabilities as MCP tools so AI agents
    (Claude Code, Cursor, Codex, OpenCode, etc.) can query the dependency
    graph directly without shelling out to the CLI.

    \b
    Available tools:
      constrictor_scan       -- scan a project and build the graph
      constrictor_impact     -- blast-radius analysis (downstream / upstream)
      constrictor_paths      -- enumerate dependency paths between two nodes
      constrictor_audit      -- list ambiguous / unresolved edges
      constrictor_dependents -- find all dependents of a file
      constrictor_summary    -- human-readable graph summary + statistics

    \b
    Examples:
      constrictor mcp serve --graph graph.json
      constrictor mcp serve --graph graph.json --auto-rescan
      constrictor mcp serve --transport sse --port 9000
    """
    import asyncio

    graph_str = str(graph.resolve()) if graph else None

    if transport == "stdio":
        from constrictor.mcp.server import run_stdio

        asyncio.run(run_stdio(default_graph_path=graph_str, auto_rescan=auto_rescan))
    elif transport == "sse":
        from constrictor.mcp.server import run_sse

        console.print(f"[bold]Constrictor MCP server (SSE) listening on http://{host}:{port}[/bold]")
        asyncio.run(run_sse(host=host, port=port, default_graph_path=graph_str, auto_rescan=auto_rescan))
    else:
        err_console.print(f"[red]Unknown transport: {transport!r}. Use 'stdio' or 'sse'.[/red]")
        raise typer.Exit(code=2)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"constrictor {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    pass


@app.command("scan")
def scan(
    path: Path = typer.Argument(
        ...,
        help="Path to the Python project root to scan.",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Write the graph JSON to this file.",
    ),
    exclude: Optional[list[str]] = typer.Option(
        None,
        "--exclude",
        "-e",
        help="Additional glob patterns to exclude.",
    ),
    exclude_file: Optional[list[Path]] = typer.Option(
        None,
        "--exclude-file",
        help="Path to a file containing additional exclude patterns.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output."),
    incremental: bool = typer.Option(
        False,
        "--incremental",
        "-i",
        help=(
            "Only re-analyze files that changed since the last scan. "
            "Maintains a .constrictor_cache/ directory under the project root. "
            "Falls back to a full scan when the cache is absent or config files changed."
        ),
    ),
    include_js: bool = typer.Option(
        False,
        "--include-js",
        help=(
            "Also parse .js, .ts, .jsx, and .tsx files and build cross-language edges "
            "between frontend HTTP calls and backend endpoints. "
            "Requires: pip install tree-sitter tree-sitter-javascript tree-sitter-typescript"
        ),
    ),
) -> None:
    """Scan a directory and build a dependency graph.

    Without -o, prints a human-readable summary to stdout.
    With -o graph.json, writes the full graph JSON to that file.

    Use --incremental to skip re-parsing files that have not changed since the
    last scan (requires a previous scan to have produced graph.json in the same
    directory, or the cache is automatically warmed on the first run).

    Use --include-js to also analyze JS/TS frontend files and stitch HTTP calls
    to their backend endpoints.
    """
    options = ScanOptions(
        root_path=path,
        exclude_patterns=list(exclude) if exclude else [],
        include_js=include_js,
    )

    if verbose:
        console.print(f"[bold]Scanning:[/bold] {path}")
        patterns = load_ignore_patterns(
            path,
            extra_exclude_files=list(exclude_file) if exclude_file else None,
            extra_patterns=list(exclude) if exclude else None,
        )
        console.print(f"[dim]Active ignore patterns: {len(patterns)}[/dim]")

    document = run_scan(options, incremental=incremental)
    stats = document.statistics
    all_warnings = document.warnings + document.unresolved

    total_count = stats.total_files
    success_count = stats.parsed_files
    fail_count = stats.failed_files

    file_label = "file" if not include_js else "Python/JS file"
    console.print(
        f"\n[bold green]Discovered {total_count} {file_label}{'s' if total_count != 1 else ''}.[/bold green] "
        f"Parsed [green]{success_count}/{total_count}[/green] successfully."
    )

    if fail_count > 0:
        console.print(
            f"[yellow]  {fail_count} file{'s' if fail_count != 1 else ''} failed to parse.[/yellow]"
        )

    if output:
        export_json(document, output)
        console.print(f"[bold]Graph written to:[/bold] {output}")
        console.print(
            f"[dim]  {stats.total_nodes} nodes, {stats.total_edges} edges[/dim]"
        )
    else:
        console.print()
        console.print(generate_summary(document))

    if verbose and all_warnings:
        console.print()
        table = Table(title="Warnings", show_lines=True)
        table.add_column("Code", style="yellow")
        table.add_column("Path")
        table.add_column("Message")

        for w in all_warnings:
            table.add_row(w.code, w.path or "", w.message)

        console.print(table)
    elif all_warnings:
        console.print(
            f"[dim]  {len(all_warnings)} warning{'s' if len(all_warnings) != 1 else ''} "
            f"(use --verbose to see details)[/dim]"
        )

    if verbose:
        console.print()
        console.print("[dim]Stage timings:[/dim]")
        if document.scan_metadata:
            for t in document.scan_metadata.timings:
                console.print(f"  [dim]{t.stage}: {t.elapsed_seconds:.3f}s[/dim]")


@app.command("audit")
def audit(
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
    """List all ambiguous and unresolved edges for human review."""
    document = load_json(graph)
    engine = GraphQueryEngine(document)
    review = engine.ambiguous_audit()

    total = len(review.unresolved_edges) + len(review.ambiguous_edges)
    console.print()
    console.print(f"[bold]Ambiguity audit:[/bold] {total} edge(s) need review.")

    if review.unresolved_edges:
        console.print()
        table = Table(title="Unresolved Edges", show_lines=True)
        table.add_column("ID", style="dim", no_wrap=True)
        table.add_column("Type", style="yellow")
        table.add_column("Display Name")
        table.add_column("File", style="dim")
        for edge in review.unresolved_edges:
            table.add_row(edge.id, edge.type.value, edge.display_name, edge.file_path or "")
        console.print(table)

    if review.ambiguous_edges:
        console.print()
        table = Table(title="Ambiguous Edges", show_lines=True)
        table.add_column("ID", style="dim", no_wrap=True)
        table.add_column("Type", style="yellow")
        table.add_column("Display Name")
        table.add_column("File", style="dim")
        for edge in review.ambiguous_edges:
            table.add_row(edge.id, edge.type.value, edge.display_name, edge.file_path or "")
        console.print(table)

    if not review.unresolved_edges and not review.ambiguous_edges:
        console.print("[green]No ambiguous or unresolved edges found.[/green]")

    console.print()


@app.command("summary")
def summary(
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
    """Print a human-readable summary of the dependency graph."""
    document = load_json(graph)
    console.print()
    console.print(generate_summary(document))
    console.print()


if __name__ == "__main__":
    app()
