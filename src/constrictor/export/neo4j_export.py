from __future__ import annotations

import csv
import io
from pathlib import Path

from constrictor.graph.models import GraphDocument


_NODES_HEADERS = [":ID", "name:string", "qualified_name:string", "type:string", ":LABEL"]
_EDGES_HEADERS = [":START_ID", ":END_ID", ":TYPE", "display_name:string", "certainty:string"]


def export_neo4j(document: GraphDocument, output_dir: Path) -> None:
    """Write nodes.csv and edges.csv for Neo4j bulk import.

    nodes.csv columns:  :ID, name:string, qualified_name:string, type:string, :LABEL
    edges.csv columns:  :START_ID, :END_ID, :TYPE, display_name:string, certainty:string
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    nodes_path = output_dir / "nodes.csv"
    with nodes_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(_NODES_HEADERS)
        for node in document.nodes:
            label = _node_type_to_label(node.type.value)
            writer.writerow([
                node.id,
                node.name,
                node.qualified_name,
                node.type.value,
                label,
            ])

    edges_path = output_dir / "edges.csv"
    with edges_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(_EDGES_HEADERS)
        for edge in document.edges:
            writer.writerow([
                edge.source_id,
                edge.target_id,
                edge.type.value,
                edge.display_name,
                edge.certainty.name,
            ])


def export_neo4j_strings(document: GraphDocument) -> tuple[str, str]:
    """Return (nodes_csv_str, edges_csv_str) without writing to disk.

    Useful for testing.
    """
    nodes_buf = io.StringIO()
    nodes_writer = csv.writer(nodes_buf)
    nodes_writer.writerow(_NODES_HEADERS)
    for node in document.nodes:
        label = _node_type_to_label(node.type.value)
        nodes_writer.writerow([
            node.id,
            node.name,
            node.qualified_name,
            node.type.value,
            label,
        ])

    edges_buf = io.StringIO()
    edges_writer = csv.writer(edges_buf)
    edges_writer.writerow(_EDGES_HEADERS)
    for edge in document.edges:
        edges_writer.writerow([
            edge.source_id,
            edge.target_id,
            edge.type.value,
            edge.display_name,
            edge.certainty.name,
        ])

    return nodes_buf.getvalue(), edges_buf.getvalue()


def _node_type_to_label(node_type: str) -> str:
    """Convert a NodeType value to a Neo4j label (title-cased, no underscores)."""
    return node_type.replace("_", "").title()
