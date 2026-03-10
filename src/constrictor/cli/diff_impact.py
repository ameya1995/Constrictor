"""CLI command: constrictor diff-impact -- blast-radius from a git diff."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from constrictor.analysis.diff import parse_diff
from constrictor.export.format_output import validate_format
from constrictor.export.json_export import load_json
from constrictor.graph.query import GraphQueryEngine

console = Console()
err_console = Console(stderr=True)


def diff_impact(
    diff_file: Optional[Path] = typer.Option(
        None,
        "--diff",
        help="Path to a unified diff file. Reads from stdin if omitted.",
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
    fmt: str = typer.Option(
        "compact",
        "--format",
        help="Output format: 'full', 'compact' (default), or 'files'.",
    ),
) -> None:
    """Find the blast radius for all changed code in a diff.

    Reads a unified diff (from git diff) and maps each changed line range to
    graph nodes, then runs merged impact analysis. Output is tiered:
    directly_changed / immediate_dependents / transitive_dependents.

    \b
    Examples:
      git diff HEAD~1 | constrictor diff-impact --graph graph.json
      constrictor diff-impact --diff my.patch --graph graph.json --format files
    """
    try:
        validate_format(fmt)
    except ValueError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=2)

    if diff_file:
        diff_text = diff_file.read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        diff_text = sys.stdin.read()
    else:
        err_console.print(
            "[red]Error:[/red] Provide a diff via --diff <file> or pipe from stdin."
        )
        raise typer.Exit(code=2)

    regions = parse_diff(diff_text)
    if not regions:
        console.print("[yellow]No changed regions found in the diff.[/yellow]")
        raise typer.Exit(code=0)

    document = load_json(graph)
    engine = GraphQueryEngine(document)
    result = engine.diff_impact(regions, fmt=fmt)

    console.print(json.dumps(result, indent=2))
