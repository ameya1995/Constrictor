import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from constrictor.core.models import Certainty, ScanMetadata
from constrictor.export.json_export import export_json, load_json
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.models import EdgeType, NodeType


def make_document():
    builder = GraphBuilder()
    builder.add_node("mod:a", NodeType.MODULE, "app.main", file_path="app/main.py")
    builder.add_node("mod:b", NodeType.MODULE, "app.utils", file_path="app/utils.py")
    builder.add_node("func:c", NodeType.FUNCTION, "greet", qualified_name="app.utils.greet")
    builder.add_edge("mod:a", "mod:b", EdgeType.IMPORTS, "main imports utils")
    builder.add_edge("mod:b", "func:c", EdgeType.CONTAINS)
    now = datetime.now(tz=timezone.utc)
    meta = ScanMetadata(
        root_path="/tmp/project",
        started_at=now,
        completed_at=now,
        python_version="3.11",
        constrictor_version="0.1.0",
    )
    return builder.build(scan_metadata=meta)


def test_export_json_returns_string():
    doc = make_document()
    result = export_json(doc)
    assert isinstance(result, str)


def test_export_json_valid_json():
    doc = make_document()
    result = export_json(doc)
    parsed = json.loads(result)
    assert "nodes" in parsed
    assert "edges" in parsed
    assert "statistics" in parsed


def test_export_json_pretty_has_indentation():
    doc = make_document()
    pretty = export_json(doc, pretty=True)
    compact = export_json(doc, pretty=False)
    assert "\n" in pretty
    assert len(pretty) > len(compact)


def test_export_json_sorted_keys():
    doc = make_document()
    result = export_json(doc, pretty=True)
    parsed = json.loads(result)
    keys = list(parsed.keys())
    assert keys == sorted(keys)


def test_export_json_writes_file():
    doc = make_document()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "graph.json"
        export_json(doc, path=path)
        assert path.exists()
        content = path.read_text()
        parsed = json.loads(content)
        assert len(parsed["nodes"]) == 3


def test_export_json_creates_parent_dirs():
    doc = make_document()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "nested" / "deep" / "graph.json"
        export_json(doc, path=path)
        assert path.exists()


def test_round_trip():
    doc = make_document()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "graph.json"
        export_json(doc, path=path)
        loaded = load_json(path)

    assert len(loaded.nodes) == len(doc.nodes)
    assert len(loaded.edges) == len(doc.edges)
    node_ids = {n.id for n in loaded.nodes}
    assert "mod:a" in node_ids
    assert "mod:b" in node_ids
    assert "func:c" in node_ids


def test_round_trip_preserves_certainty():
    builder = GraphBuilder()
    builder.add_node("mod:a", NodeType.MODULE, "a", certainty=Certainty.INFERRED)
    doc = builder.build()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "graph.json"
        export_json(doc, path=path)
        loaded = load_json(path)
    assert loaded.nodes[0].certainty == Certainty.INFERRED


def test_round_trip_stable_ordering():
    """Two exports of the same document should produce identical JSON."""
    doc = make_document()
    json1 = export_json(doc, pretty=True)
    json2 = export_json(doc, pretty=True)
    assert json1 == json2


def test_round_trip_preserves_metadata():
    builder = GraphBuilder()
    builder.add_node("mod:a", NodeType.MODULE, "a", metadata={"framework": "fastapi"})
    doc = builder.build()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "graph.json"
        export_json(doc, path=path)
        loaded = load_json(path)
    assert loaded.nodes[0].metadata["framework"] == "fastapi"
