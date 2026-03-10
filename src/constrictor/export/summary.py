from __future__ import annotations

from constrictor.graph.models import GraphDocument


def generate_summary(document: GraphDocument) -> str:
    """Generate a one-paragraph human-readable summary of the graph document.

    Useful both as CLI output and as context passed to an AI agent.
    """
    stats = document.statistics
    meta = document.scan_metadata

    parts: list[str] = []

    if meta:
        parts.append(f"Scanned: {meta.root_path}")

    file_info = f"{stats.parsed_files} Python files parsed"
    if stats.failed_files:
        file_info += f" ({stats.failed_files} failed)"
    parts.append(file_info)

    parts.append(f"{stats.total_nodes} nodes and {stats.total_edges} edges in the graph")

    if stats.node_type_counts:
        top_nodes = sorted(stats.node_type_counts.items(), key=lambda x: -x[1])
        node_breakdown = ", ".join(f"{count} {ntype.lower()}s" for ntype, count in top_nodes[:5])
        parts.append(f"Node breakdown: {node_breakdown}")

    if stats.edge_type_counts:
        top_edges = sorted(stats.edge_type_counts.items(), key=lambda x: -x[1])
        edge_breakdown = ", ".join(f"{count} {etype.lower()}" for etype, count in top_edges[:5])
        parts.append(f"Edge breakdown: {edge_breakdown}")

    if stats.service_count:
        parts.append(f"{stats.service_count} service(s) detected")

    if stats.cross_component_edge_count:
        parts.append(f"{stats.cross_component_edge_count} cross-component edge(s)")

    if stats.warning_count:
        parts.append(f"{stats.warning_count} warning(s) (including {len(document.unresolved)} unresolved)")

    return ". ".join(parts) + "."
