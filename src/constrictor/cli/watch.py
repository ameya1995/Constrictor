from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from constrictor.core.models import ScanOptions
from constrictor.core.orchestrator import run_scan
from constrictor.export.json_export import export_json

console = Console()
err_console = Console(stderr=True)

WATCH_EXTENSIONS = {".py", ".toml", ".yml", ".yaml", ".cfg", ".txt"}


def watch(
    path: Path = typer.Argument(
        ...,
        help="Path to the Python project root to watch.",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    output: Optional[Path] = typer.Option(
        Path("graph.json"),
        "--output",
        "-o",
        help="Path to write the graph JSON on each rescan.",
    ),
    debounce_ms: int = typer.Option(
        1500,
        "--debounce-ms",
        help="Debounce delay in milliseconds between rescans.",
    ),
    exclude: Optional[list[str]] = typer.Option(
        None,
        "--exclude",
        "-e",
        help="Additional glob patterns to exclude.",
    ),
    incremental: bool = typer.Option(
        True,
        "--incremental/--no-incremental",
        help=(
            "Use incremental scanning (default: on). Only re-analyzes changed files, "
            "making each rescan significantly faster. Use --no-incremental to force a "
            "full rescan on every file change."
        ),
    ),
) -> None:
    """Watch a directory for changes and rescan automatically.

    Monitors .py, .toml, .yml, .yaml, .cfg, and .txt files.
    On change, re-runs the scan pipeline and writes updated graph JSON.
    Incremental mode is enabled by default: only changed files are re-analyzed.
    """
    try:
        from watchfiles import watch as watchfiles_watch
    except ImportError:
        err_console.print(
            "[red]Error:[/red] watchfiles is required for watch mode. "
            "Install it with: pip install watchfiles"
        )
        raise typer.Exit(1)

    options = ScanOptions(
        root_path=path,
        exclude_patterns=list(exclude) if exclude else [],
    )

    mode_label = "[cyan]incremental[/cyan]" if incremental else "[yellow]full[/yellow]"
    console.print(f"[bold green]Watching:[/bold green] {path}  [{mode_label} mode]")
    console.print(
        f"[dim]Output: {output}  |  Debounce: {debounce_ms}ms  |  "
        f"Press Ctrl+C to stop.[/dim]"
    )
    console.print()

    def _do_scan() -> None:
        start = time.monotonic()
        try:
            document = run_scan(options, incremental=incremental)
            if output:
                export_json(document, output)
            elapsed = time.monotonic() - start
            stats = document.statistics
            console.print(
                f"[green]✓[/green] Rescan complete in [bold]{elapsed:.2f}s[/bold]  "
                f"[dim]({stats.total_nodes} nodes, {stats.total_edges} edges)[/dim]"
            )
        except Exception as exc:
            console.print(f"[red]✗ Rescan failed:[/red] {exc}")

    _do_scan()

    debounce_s = debounce_ms / 1000.0

    try:
        pending_changes: list[str] = []
        last_change_time: float = 0.0

        for changes in watchfiles_watch(path, yield_on_timeout=True, watch_filter=_ext_filter):
            now = time.monotonic()

            for _change_type, changed_path in changes:
                pending_changes.append(changed_path)

            if pending_changes:
                last_change_time = now

            if pending_changes and (now - last_change_time) >= debounce_s:
                trigger = pending_changes[0]
                pending_changes.clear()
                console.print(
                    f"[bold]Rescan triggered by:[/bold] {trigger}"
                )
                _do_scan()
    except KeyboardInterrupt:
        console.print("\n[dim]Watch mode stopped.[/dim]")


def _ext_filter(change, path: str) -> bool:
    """Only watch files with relevant extensions."""
    return Path(path).suffix in WATCH_EXTENSIONS
