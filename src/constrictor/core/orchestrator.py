from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from constrictor import __version__
from constrictor.analysis.calls import CallGraphExtractor
from constrictor.analysis.classes import ClassHierarchyExtractor
from constrictor.analysis.django import DjangoExtractor
from constrictor.analysis.fastapi import FastAPIExtractor
from constrictor.analysis.flask import FlaskExtractor
from constrictor.analysis.http_clients import HTTPClientExtractor
from constrictor.analysis.imports import ImportExtractor
from constrictor.analysis.js_calls import JSCallExtractor
from constrictor.analysis.js_http import JSHttpExtractor
from constrictor.analysis.js_imports import JSImportExtractor
from constrictor.analysis.sqlalchemy import SQLAlchemyExtractor
from constrictor.analysis.topology import TopologyContributor
from constrictor.analysis.type_annotations import TypeAnnotationExtractor
from constrictor.core.cache import FileCache, FileFragment
from constrictor.core.js_parser import ParsedJSModule, parse_all_js
from constrictor.core.models import ScanMetadata, ScanOptions, ScanWarning, StageTiming
from constrictor.core.parser import ParsedModule, parse_all
from constrictor.core.scanner import scan_directory
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.models import EdgeType, GraphDocument, GraphEdge, GraphNode, NodeType


def _build_contributors(config_files: list[Path]) -> tuple[list, TopologyContributor]:
    """Construct the ordered list of extractors and return them alongside the topology instance."""
    topology_contributor = TopologyContributor(config_files=config_files)
    contributors = [
        ImportExtractor(),
        ClassHierarchyExtractor(),
        CallGraphExtractor(),
        FastAPIExtractor(),
        FlaskExtractor(),
        DjangoExtractor(),
        SQLAlchemyExtractor(),
        HTTPClientExtractor(),
        TypeAnnotationExtractor(),
        topology_contributor,
    ]
    return contributors, topology_contributor


def _build_js_contributors() -> tuple[JSImportExtractor, JSCallExtractor, JSHttpExtractor]:
    """Construct the ordered list of JS/TS extractors."""
    return JSImportExtractor(), JSCallExtractor(), JSHttpExtractor()


def _run_js_contributors(
    js_extractors: tuple[JSImportExtractor, JSCallExtractor, JSHttpExtractor],
    parsed_js_modules: list[ParsedJSModule],
    builder: GraphBuilder,
    all_warnings: list[ScanWarning],
    timings: list[StageTiming],
) -> None:
    js_imports, js_calls, js_http = js_extractors
    for extractor in (js_imports, js_calls, js_http):
        t0 = time.perf_counter()
        extractor.contribute_js(parsed_js_modules, builder, all_warnings)
        timings.append(
            StageTiming(
                stage=f"extract:{extractor.name}",
                elapsed_seconds=time.perf_counter() - t0,
            )
        )


def _run_js_post_process(
    js_extractors: tuple[JSImportExtractor, JSCallExtractor, JSHttpExtractor],
    builder: GraphBuilder,
    timings: list[StageTiming],
) -> None:
    t0 = time.perf_counter()
    for extractor in js_extractors:
        extractor.post_process(builder)
    timings.append(StageTiming(stage="post_process:js", elapsed_seconds=time.perf_counter() - t0))


def _run_contributors(
    contributors: list,
    parsed_modules: list[ParsedModule],
    builder: GraphBuilder,
    all_warnings: list[ScanWarning],
    timings: list[StageTiming],
) -> None:
    for contributor in contributors:
        t0 = time.perf_counter()
        contributor.contribute(parsed_modules, builder, all_warnings)
        timings.append(
            StageTiming(
                stage=f"extract:{contributor.name}",
                elapsed_seconds=time.perf_counter() - t0,
            )
        )


def _run_post_process(
    contributors: list,
    builder: GraphBuilder,
    timings: list[StageTiming],
) -> None:
    t0 = time.perf_counter()
    for contributor in contributors:
        contributor.post_process(builder)
    timings.append(StageTiming(stage="post_process", elapsed_seconds=time.perf_counter() - t0))


def _finalize_document(
    builder: GraphBuilder,
    all_warnings: list[ScanWarning],
    started_at: datetime,
    timings: list[StageTiming],
    total_files: int,
    parsed_files: int,
    failed_files: int,
    options: ScanOptions,
) -> GraphDocument:
    completed_at = datetime.now(timezone.utc)
    scan_metadata = ScanMetadata(
        root_path=str(options.root_path),
        started_at=started_at,
        completed_at=completed_at,
        python_version=sys.version,
        constrictor_version=__version__,
        timings=timings,
    )

    document = builder.build(scan_metadata=scan_metadata, warnings=all_warnings)

    service_count = sum(
        1 for n in document.nodes if n.type in (NodeType.SERVICE, NodeType.COMPONENT)
    )
    cross_component_edge_count = sum(
        1 for e in document.edges if e.type == EdgeType.CROSSES_COMPONENT_BOUNDARY
    )

    return document.model_copy(
        update={
            "statistics": document.statistics.model_copy(
                update={
                    "total_files": total_files,
                    "parsed_files": parsed_files,
                    "failed_files": failed_files,
                    "service_count": service_count,
                    "cross_component_edge_count": cross_component_edge_count,
                }
            )
        }
    )


def run_scan(options: ScanOptions, incremental: bool = False) -> GraphDocument:
    """Run the scan pipeline and return the completed GraphDocument.

    When ``incremental=True``, a `.constrictor_cache/` directory is maintained
    under ``options.root_path``.  Only changed, added, or removed files trigger
    re-extraction; unchanged files' graph fragments are loaded from cache.

    Falls back to a full scan automatically when:
    - The cache directory does not exist or is empty.
    - Any config file (.constrictor_ignore, docker-compose.yml, pyproject.toml,
      Dockerfile, Procfile) has changed since the last scan.
    """
    if incremental:
        return _run_incremental(options)
    return _run_full(options)


# ---------------------------------------------------------------------------
# Full scan
# ---------------------------------------------------------------------------

def _run_full(options: ScanOptions) -> GraphDocument:
    """Perform a complete (non-incremental) scan."""
    started_at = datetime.now(timezone.utc)
    timings: list[StageTiming] = []
    all_warnings: list[ScanWarning] = []

    t0 = time.perf_counter()
    scan_result = scan_directory(options)
    all_warnings.extend(scan_result.warnings)
    timings.append(StageTiming(stage="scan", elapsed_seconds=time.perf_counter() - t0))

    t0 = time.perf_counter()
    parsed_modules, parse_warnings = parse_all(scan_result.python_files, options.root_path)
    all_warnings.extend(parse_warnings)
    timings.append(StageTiming(stage="parse", elapsed_seconds=time.perf_counter() - t0))

    builder = GraphBuilder()
    _total_files = len(scan_result.python_files)
    _parsed_files = len(parsed_modules)
    _failed_files = len(parse_warnings)

    contributors, _ = _build_contributors(scan_result.config_files)
    _run_contributors(contributors, parsed_modules, builder, all_warnings, timings)

    # JS/TS pipeline (optional)
    if options.include_js and scan_result.js_files:
        t0 = time.perf_counter()
        parsed_js_modules, js_parse_warnings = parse_all_js(scan_result.js_files, options.root_path)
        all_warnings.extend(js_parse_warnings)
        timings.append(StageTiming(stage="parse:js", elapsed_seconds=time.perf_counter() - t0))

        _total_files += len(scan_result.js_files)
        _parsed_files += len(parsed_js_modules)
        _failed_files += len(js_parse_warnings)

        js_extractors = _build_js_contributors()
        _run_js_contributors(js_extractors, parsed_js_modules, builder, all_warnings, timings)
        # JS post-process (cross-language stitching) runs AFTER Python post-process
        _run_post_process(contributors, builder, timings)
        _run_js_post_process(js_extractors, builder, timings)
    else:
        _run_post_process(contributors, builder, timings)

    return _finalize_document(
        builder,
        all_warnings,
        started_at,
        timings,
        _total_files,
        _parsed_files,
        _failed_files,
        options,
    )


# ---------------------------------------------------------------------------
# Incremental scan
# ---------------------------------------------------------------------------

def _run_incremental(options: ScanOptions) -> GraphDocument:
    """Perform an incremental scan, re-analyzing only changed/added files."""
    started_at = datetime.now(timezone.utc)
    timings: list[StageTiming] = []
    all_warnings: list[ScanWarning] = []

    cache = FileCache(options.root_path)
    cache.load()

    # Config-file changes always require a full rescan.
    if cache.is_empty or cache.config_files_changed(options.root_path):
        timings.append(
            StageTiming(stage="cache:miss_full_rescan", elapsed_seconds=0.0)
        )
        doc = _run_full(options)
        # After a full scan, persist hashes and fragments so future incremental
        # runs can start from a warm cache.
        _warm_cache(cache, options, doc)
        return doc

    # Discover current files.
    t0 = time.perf_counter()
    scan_result = scan_directory(options)
    all_warnings.extend(scan_result.warnings)
    timings.append(StageTiming(stage="scan", elapsed_seconds=time.perf_counter() - t0))

    # Diff against cache.
    t0 = time.perf_counter()
    diff = cache.diff(scan_result.python_files)
    timings.append(StageTiming(stage="cache:diff", elapsed_seconds=time.perf_counter() - t0))

    # Load previous document to seed the builder with unchanged fragments.
    # If no graph.json is available (e.g. on the very first incremental run
    # after cache was warmed without producing a file), fall back to full scan.
    prev_graph_path = options.root_path / "graph.json"
    if not prev_graph_path.exists():
        doc = _run_full(options)
        _warm_cache(cache, options, doc)
        return doc

    from constrictor.export.json_export import load_json

    try:
        prev_document = load_json(prev_graph_path)
    except Exception:
        doc = _run_full(options)
        _warm_cache(cache, options, doc)
        return doc

    # Build set of "dirty" file paths (changed + removed).
    dirty_paths: set[str] = {
        str(p.resolve()) for p in diff.changed + diff.removed
    }

    # Seed the builder with nodes/edges from UNCHANGED files.
    t0 = time.perf_counter()
    builder = GraphBuilder()
    _seed_builder_from_document(builder, prev_document, dirty_paths)
    timings.append(
        StageTiming(stage="cache:seed_unchanged", elapsed_seconds=time.perf_counter() - t0)
    )

    # Parse only the files that need re-analysis.
    t0 = time.perf_counter()
    files_to_reanalyze = diff.needs_reanalysis
    if files_to_reanalyze:
        parsed_modules, parse_warnings = parse_all(files_to_reanalyze, options.root_path)
    else:
        parsed_modules, parse_warnings = [], []
    all_warnings.extend(parse_warnings)
    timings.append(StageTiming(stage="parse:incremental", elapsed_seconds=time.perf_counter() - t0))

    _total_files = len(scan_result.python_files)
    _parsed_files = len(diff.unchanged) + len(parsed_modules)
    _failed_files = len(parse_warnings)

    # Run extractors on the new/changed modules only.
    if parsed_modules:
        contributors, _ = _build_contributors(scan_result.config_files)
        _run_contributors(contributors, parsed_modules, builder, all_warnings, timings)
    else:
        contributors, _ = _build_contributors(scan_result.config_files)

    # JS/TS pipeline (incremental: re-run all JS files for simplicity — JS cache TBD)
    if options.include_js and scan_result.js_files:
        t0 = time.perf_counter()
        parsed_js_modules, js_parse_warnings = parse_all_js(scan_result.js_files, options.root_path)
        all_warnings.extend(js_parse_warnings)
        timings.append(StageTiming(stage="parse:js", elapsed_seconds=time.perf_counter() - t0))

        js_extractors = _build_js_contributors()
        _run_js_contributors(js_extractors, parsed_js_modules, builder, all_warnings, timings)
        _run_post_process(contributors, builder, timings)
        _run_js_post_process(js_extractors, builder, timings)
    else:
        # Topology post-process always runs (cross-boundary tagging needs the full graph).
        _run_post_process(contributors, builder, timings)

    document = _finalize_document(
        builder,
        all_warnings,
        started_at,
        timings,
        _total_files,
        _parsed_files,
        _failed_files,
        options,
    )

    # Update cache: remove stale hashes/fragments, add new ones.
    t0 = time.perf_counter()
    for p in diff.removed + diff.changed:
        cache.delete_fragment(p)
    cache.remove_hashes(diff.removed)
    cache.update_hashes(files_to_reanalyze + list(diff.unchanged))
    cache.update_config_hashes(options.root_path)

    # Store fragments for newly analyzed files.
    _store_fragments(cache, document, files_to_reanalyze)

    cache.save()
    timings.append(
        StageTiming(stage="cache:update", elapsed_seconds=time.perf_counter() - t0)
    )

    return document


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_builder_from_document(
    builder: GraphBuilder,
    prev_document: GraphDocument,
    dirty_paths: set[str],
) -> None:
    """Replay all nodes/edges from prev_document that don't come from dirty files."""
    for node in prev_document.nodes:
        node_path = str(Path(node.file_path).resolve()) if node.file_path else None
        if node_path in dirty_paths:
            continue
        builder.add_node(
            id=node.id,
            type=node.type,
            name=node.name,
            qualified_name=node.qualified_name,
            display_name=node.display_name,
            file_path=node.file_path,
            line_number=node.line_number,
            column=node.column,
            certainty=node.certainty,
            metadata=dict(node.metadata),
        )

    for edge in prev_document.edges:
        edge_path = str(Path(edge.file_path).resolve()) if edge.file_path else None
        if edge_path in dirty_paths:
            continue
        builder.add_edge(
            source_id=edge.source_id,
            target_id=edge.target_id,
            type=edge.type,
            display_name=edge.display_name,
            file_path=edge.file_path,
            line_number=edge.line_number,
            certainty=edge.certainty,
            metadata=dict(edge.metadata),
        )


def _collect_fragments(
    document: GraphDocument,
    files: list[Path],
) -> list[FileFragment]:
    """Extract the subset of nodes/edges from `document` that belong to `files`."""
    file_keys: set[str] = {str(p.resolve()) for p in files}
    fragments: list[FileFragment] = []

    for p in files:
        key = str(p.resolve())
        nodes: list[GraphNode] = [
            n for n in document.nodes
            if n.file_path and str(Path(n.file_path).resolve()) == key
        ]
        edges: list[GraphEdge] = [
            e for e in document.edges
            if e.file_path and str(Path(e.file_path).resolve()) == key
        ]
        fragments.append(FileFragment(file_path=str(p), nodes=nodes, edges=edges))

    return fragments


def _store_fragments(
    cache: FileCache,
    document: GraphDocument,
    files: list[Path],
) -> None:
    """Compute and persist fragments for the given files."""
    fragments = _collect_fragments(document, files)
    cache.store_fragments(fragments)


def _warm_cache(cache: FileCache, options: ScanOptions, document: GraphDocument) -> None:
    """After a full scan, populate the cache so the next run can be incremental."""
    from constrictor.core.scanner import scan_directory as _scan

    scan_result = _scan(options)
    all_files = scan_result.python_files

    cache.update_hashes(all_files)
    cache.update_config_hashes(options.root_path)
    _store_fragments(cache, document, all_files)
    cache.save()
