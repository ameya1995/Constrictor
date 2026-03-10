from datetime import datetime, timezone

import pytest

from constrictor.core.models import Certainty, ScanMetadata, ScanWarning
from constrictor.graph.builder import GraphBuilder, _merge_metadata
from constrictor.graph.models import EdgeType, NodeType


def make_metadata() -> ScanMetadata:
    now = datetime.now(tz=timezone.utc)
    return ScanMetadata(
        root_path="/tmp/project",
        started_at=now,
        completed_at=now,
        python_version="3.11",
        constrictor_version="0.1.0",
    )


def test_add_node_basic():
    builder = GraphBuilder()
    node = builder.add_node("mod:abc", NodeType.MODULE, "app.main")
    assert node.id == "mod:abc"
    assert node.type == NodeType.MODULE
    assert node.name == "app.main"
    assert node.certainty == Certainty.EXACT


def test_add_node_defaults_qualified_and_display_name():
    builder = GraphBuilder()
    node = builder.add_node("mod:abc", NodeType.MODULE, "app.main")
    assert node.qualified_name == "app.main"
    assert node.display_name == "app.main"


def test_add_node_merge_higher_certainty_wins():
    builder = GraphBuilder()
    builder.add_node("mod:abc", NodeType.MODULE, "app.main", certainty=Certainty.UNRESOLVED)
    node = builder.add_node("mod:abc", NodeType.MODULE, "app.main", certainty=Certainty.EXACT)
    assert node.certainty == Certainty.EXACT


def test_add_node_merge_lower_certainty_does_not_downgrade():
    builder = GraphBuilder()
    builder.add_node("mod:abc", NodeType.MODULE, "app.main", certainty=Certainty.EXACT)
    node = builder.add_node("mod:abc", NodeType.MODULE, "app.main", certainty=Certainty.UNRESOLVED)
    assert node.certainty == Certainty.EXACT


def test_add_node_merge_metadata():
    builder = GraphBuilder()
    builder.add_node("mod:abc", NodeType.MODULE, "app.main", metadata={"key": "old"})
    node = builder.add_node("mod:abc", NodeType.MODULE, "app.main", metadata={"key2": "new"})
    assert node.metadata["key"] == "old"
    assert node.metadata["key2"] == "new"


def test_add_node_merge_metadata_conflict_concatenates():
    builder = GraphBuilder()
    builder.add_node("mod:abc", NodeType.MODULE, "app.main", metadata={"k": "v1"})
    node = builder.add_node("mod:abc", NodeType.MODULE, "app.main", metadata={"k": "v2"})
    assert node.metadata["k"] == "v1 | v2"


def test_add_node_merge_same_metadata_no_duplicate():
    builder = GraphBuilder()
    builder.add_node("mod:abc", NodeType.MODULE, "app.main", metadata={"k": "v1"})
    node = builder.add_node("mod:abc", NodeType.MODULE, "app.main", metadata={"k": "v1"})
    assert node.metadata["k"] == "v1"


def test_add_edge_auto_generates_id():
    builder = GraphBuilder()
    builder.add_node("mod:a", NodeType.MODULE, "app.main")
    builder.add_node("mod:b", NodeType.MODULE, "app.utils")
    edge = builder.add_edge("mod:a", "mod:b", EdgeType.IMPORTS)
    assert edge.id.startswith("edge:")


def test_add_edge_deterministic_id():
    b1 = GraphBuilder()
    b1.add_node("mod:a", NodeType.MODULE, "a")
    b1.add_node("mod:b", NodeType.MODULE, "b")
    e1 = b1.add_edge("mod:a", "mod:b", EdgeType.IMPORTS)

    b2 = GraphBuilder()
    b2.add_node("mod:a", NodeType.MODULE, "a")
    b2.add_node("mod:b", NodeType.MODULE, "b")
    e2 = b2.add_edge("mod:a", "mod:b", EdgeType.IMPORTS)

    assert e1.id == e2.id


def test_add_edge_merge_on_duplicate():
    builder = GraphBuilder()
    builder.add_node("mod:a", NodeType.MODULE, "a")
    builder.add_node("mod:b", NodeType.MODULE, "b")
    builder.add_edge("mod:a", "mod:b", EdgeType.IMPORTS, certainty=Certainty.AMBIGUOUS)
    edge = builder.add_edge("mod:a", "mod:b", EdgeType.IMPORTS, certainty=Certainty.EXACT)
    assert edge.certainty == Certainty.EXACT
    assert len(builder._edges) == 1


def test_build_computes_statistics():
    builder = GraphBuilder()
    builder.add_node("mod:a", NodeType.MODULE, "a")
    builder.add_node("func:b", NodeType.FUNCTION, "b")
    builder.add_edge("mod:a", "func:b", EdgeType.CONTAINS)
    doc = builder.build()
    assert doc.statistics.total_nodes == 2
    assert doc.statistics.total_edges == 1
    assert doc.statistics.node_type_counts["MODULE"] == 1
    assert doc.statistics.node_type_counts["FUNCTION"] == 1
    assert doc.statistics.edge_type_counts["CONTAINS"] == 1


def test_build_separates_unresolved_warnings():
    builder = GraphBuilder()
    warnings = [
        ScanWarning(code="W001", message="Syntax error", certainty=Certainty.UNRESOLVED),
        ScanWarning(code="W002", message="Import warning", certainty=Certainty.AMBIGUOUS),
    ]
    doc = builder.build(warnings=warnings)
    assert len(doc.unresolved) == 1
    assert doc.unresolved[0].code == "W001"
    assert len(doc.warnings) == 1
    assert doc.warnings[0].code == "W002"


def test_build_includes_scan_metadata():
    builder = GraphBuilder()
    meta = make_metadata()
    doc = builder.build(scan_metadata=meta)
    assert doc.scan_metadata is not None
    assert doc.scan_metadata.root_path == "/tmp/project"


def test_build_sorts_nodes_and_edges():
    builder = GraphBuilder()
    builder.add_node("mod:zzz", NodeType.MODULE, "z")
    builder.add_node("mod:aaa", NodeType.MODULE, "a")
    doc = builder.build()
    ids = [n.id for n in doc.nodes]
    assert ids == sorted(ids)


def test_empty_builder():
    builder = GraphBuilder()
    doc = builder.build()
    assert doc.nodes == []
    assert doc.edges == []
    assert doc.statistics.total_nodes == 0
    assert doc.statistics.total_edges == 0


def test_merge_metadata_helper():
    result = _merge_metadata({"a": "1", "b": "old"}, {"b": "new", "c": "3"})
    assert result["a"] == "1"
    assert result["b"] == "old | new"
    assert result["c"] == "3"


def test_merge_metadata_same_value_no_duplicate():
    result = _merge_metadata({"a": "same"}, {"a": "same"})
    assert result["a"] == "same"
