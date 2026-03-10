"""Integration tests for Constrictor.

Covers:
- End-to-end scans of every fixture project
- Determinism: running the scan twice yields identical output
- Round-trip: export JSON → load → re-export yields identical output
- Query results verified against manually computed expected values
- Self-scan: Constrictor can analyse its own source tree
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from constrictor.core.models import ScanOptions
from constrictor.core.orchestrator import run_scan
from constrictor.export.json_export import export_json, load_json
from constrictor.graph.models import EdgeType, GraphDocument, NodeType
from constrictor.graph.query import GraphQueryEngine, NodeNotFoundError

FIXTURES = Path(__file__).parent / "fixtures"

SIMPLE = FIXTURES / "simple_project"
FASTAPI = FIXTURES / "fastapi_project"
FLASK = FIXTURES / "flask_project"
SQLA = FIXTURES / "sqlalchemy_project"
FULLSTACK = FIXTURES / "fullstack_project"

SRC_ROOT = Path(__file__).parent.parent / "src" / "constrictor"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scan(root: Path) -> GraphDocument:
    return run_scan(ScanOptions(root_path=root))


def _json_roundtrip(doc: GraphDocument) -> GraphDocument:
    json_str = export_json(doc)
    data = json.loads(json_str)
    return GraphDocument.model_validate(data)


# ---------------------------------------------------------------------------
# Simple project: end-to-end
# ---------------------------------------------------------------------------

class TestSimpleProjectIntegration:
    @pytest.fixture(scope="class")
    def doc(self):
        return _scan(SIMPLE)

    def test_returns_document(self, doc):
        assert isinstance(doc, GraphDocument)

    def test_has_module_nodes(self, doc):
        modules = [n for n in doc.nodes if n.type == NodeType.MODULE]
        names = {n.name for n in modules}
        assert "app.main" in names
        assert "app.utils" in names
        assert "app.models" in names

    def test_has_function_nodes(self, doc):
        func_names = {n.name for n in doc.nodes if n.type == NodeType.FUNCTION}
        assert "greet" in func_names
        assert "helper" in func_names
        assert "run_app" in func_names

    def test_has_class_node_user(self, doc):
        class_names = {n.name for n in doc.nodes if n.type == NodeType.CLASS}
        assert "User" in class_names

    def test_import_edges_present(self, doc):
        import_edges = [
            e for e in doc.edges
            if e.type in (EdgeType.IMPORTS, EdgeType.IMPORTS_FROM)
        ]
        assert import_edges

    def test_calls_edges_present(self, doc):
        call_edges = [e for e in doc.edges if e.type == EdgeType.CALLS]
        assert call_edges

    def test_contains_edges_present(self, doc):
        contains = [e for e in doc.edges if e.type == EdgeType.CONTAINS]
        assert contains

    def test_scan_metadata_populated(self, doc):
        assert doc.scan_metadata is not None
        assert doc.scan_metadata.constrictor_version

    def test_statistics_match_reality(self, doc):
        stats = doc.statistics
        assert stats.total_nodes == len(doc.nodes)
        assert stats.total_edges == len(doc.edges)
        assert stats.total_files >= 4
        assert stats.failed_files == 0

    def test_query_impact_greet(self, doc):
        engine = GraphQueryEngine(doc)
        subgraph = engine.impact("greet", direction="upstream")
        # run_app calls greet, so it should appear in upstream impact
        node_names = {n.name for n in subgraph.nodes}
        assert "run_app" in node_names

    def test_query_resolve_by_name(self, doc):
        engine = GraphQueryEngine(doc)
        node = engine.resolve_node("greet")
        assert node.name == "greet"

    def test_query_unknown_node_raises(self, doc):
        engine = GraphQueryEngine(doc)
        with pytest.raises(NodeNotFoundError):
            engine.resolve_node("nonexistent_xyz_987")


# ---------------------------------------------------------------------------
# Determinism: two scans produce identical output
# ---------------------------------------------------------------------------

class TestDeterminism:
    @pytest.mark.parametrize("fixture_path", [SIMPLE, FASTAPI, FLASK, SQLA])
    def test_scan_is_deterministic(self, fixture_path: Path):
        doc1 = _scan(fixture_path)
        doc2 = _scan(fixture_path)

        assert doc1.statistics.total_nodes == doc2.statistics.total_nodes
        assert doc1.statistics.total_edges == doc2.statistics.total_edges

        ids1 = sorted(n.id for n in doc1.nodes)
        ids2 = sorted(n.id for n in doc2.nodes)
        assert ids1 == ids2

        edge_ids1 = sorted(e.id for e in doc1.edges)
        edge_ids2 = sorted(e.id for e in doc2.edges)
        assert edge_ids1 == edge_ids2

    def test_json_output_is_deterministic(self, tmp_path: Path):
        """Node/edge content is deterministic; timestamps excluded."""
        doc1 = _scan(SIMPLE)
        doc2 = _scan(SIMPLE)

        data1 = json.loads(export_json(doc1))
        data2 = json.loads(export_json(doc2))

        # Strip the timestamps from scan_metadata before comparing
        for data in (data1, data2):
            if data.get("scan_metadata"):
                data["scan_metadata"].pop("started_at", None)
                data["scan_metadata"].pop("completed_at", None)
                if data["scan_metadata"].get("timings"):
                    data["scan_metadata"]["timings"] = []

        assert data1 == data2


# ---------------------------------------------------------------------------
# Round-trip: export → load → re-export produces identical JSON
# ---------------------------------------------------------------------------

class TestRoundTrip:
    @pytest.mark.parametrize("fixture_path", [SIMPLE, FASTAPI])
    def test_json_roundtrip(self, fixture_path: Path):
        original = _scan(fixture_path)
        json1 = export_json(original, pretty=True)
        reloaded = _json_roundtrip(original)
        json2 = export_json(reloaded, pretty=True)
        assert json1 == json2

    def test_file_roundtrip(self, tmp_path: Path):
        original = _scan(SIMPLE)
        path = tmp_path / "graph.json"
        export_json(original, path=path)

        reloaded = load_json(path)
        assert len(reloaded.nodes) == len(original.nodes)
        assert len(reloaded.edges) == len(original.edges)

        path2 = tmp_path / "graph2.json"
        export_json(reloaded, path=path2)

        assert path.read_text() == path2.read_text()


# ---------------------------------------------------------------------------
# FastAPI project: endpoints and dependencies
# ---------------------------------------------------------------------------

class TestFastAPIProjectIntegration:
    @pytest.fixture(scope="class")
    def doc(self):
        return _scan(FASTAPI)

    def test_endpoint_nodes_present(self, doc):
        endpoints = [n for n in doc.nodes if n.type == NodeType.ENDPOINT]
        assert endpoints, "Expected ENDPOINT nodes in FastAPI fixture"

    def test_get_users_endpoint(self, doc):
        endpoints = [n for n in doc.nodes if n.type == NodeType.ENDPOINT]
        methods = {n.metadata.get("http_method", "").upper() for n in endpoints}
        assert "GET" in methods or "POST" in methods

    def test_exposes_endpoint_edges(self, doc):
        ee = [e for e in doc.edges if e.type == EdgeType.EXPOSES_ENDPOINT]
        assert ee, "Expected EXPOSES_ENDPOINT edges"

    def test_calls_http_edges(self, doc):
        http = [e for e in doc.edges if e.type == EdgeType.CALLS_HTTP]
        assert http, "Expected CALLS_HTTP edges from user_service"

    def test_injects_dependency_edges(self, doc):
        inj = [e for e in doc.edges if e.type == EdgeType.INJECTS_DEPENDENCY]
        assert inj, "Expected INJECTS_DEPENDENCY edges (Depends(...))"

    def test_no_failed_files(self, doc):
        assert doc.statistics.failed_files == 0


# ---------------------------------------------------------------------------
# SQLAlchemy project: models and relationships
# ---------------------------------------------------------------------------

class TestSQLAlchemyProjectIntegration:
    @pytest.fixture(scope="class")
    def doc(self):
        return _scan(SQLA)

    def test_sqlalchemy_model_nodes(self, doc):
        models = [n for n in doc.nodes if n.type == NodeType.SQLALCHEMY_MODEL]
        assert models, "Expected SQLALCHEMY_MODEL nodes"

    def test_table_nodes(self, doc):
        tables = [n for n in doc.nodes if n.type == NodeType.TABLE]
        assert tables, "Expected TABLE nodes"

    def test_defines_model_edges(self, doc):
        dm = [e for e in doc.edges if e.type == EdgeType.DEFINES_MODEL]
        assert dm, "Expected DEFINES_MODEL edges"

    def test_foreign_key_edges(self, doc):
        fk = [e for e in doc.edges if e.type == EdgeType.FOREIGN_KEY]
        assert fk, "Expected FOREIGN_KEY edges"


# ---------------------------------------------------------------------------
# Flask project: routes
# ---------------------------------------------------------------------------

class TestFlaskProjectIntegration:
    @pytest.fixture(scope="class")
    def doc(self):
        return _scan(FLASK)

    def test_endpoint_nodes_present(self, doc):
        endpoints = [n for n in doc.nodes if n.type == NodeType.ENDPOINT]
        assert endpoints, "Expected ENDPOINT nodes in Flask fixture"

    def test_exposes_endpoint_edges(self, doc):
        ee = [e for e in doc.edges if e.type == EdgeType.EXPOSES_ENDPOINT]
        assert ee


# ---------------------------------------------------------------------------
# Fullstack project: services, cross-boundary edges
# ---------------------------------------------------------------------------

class TestFullstackProjectIntegration:
    @pytest.fixture(scope="class")
    def doc(self):
        return _scan(FULLSTACK)

    def test_service_nodes_present(self, doc):
        services = [
            n for n in doc.nodes
            if n.type in (NodeType.SERVICE, NodeType.COMPONENT)
        ]
        assert services, "Expected SERVICE or COMPONENT nodes in fullstack fixture"

    def test_belongs_to_service_edges(self, doc):
        bts = [e for e in doc.edges if e.type == EdgeType.BELONGS_TO_SERVICE]
        assert bts, "Expected BELONGS_TO_SERVICE edges"

    def test_statistics_counts_services(self, doc):
        assert doc.statistics.service_count > 0

    def test_no_failed_files(self, doc):
        assert doc.statistics.failed_files == 0

    def test_scan_is_deterministic(self):
        doc1 = _scan(FULLSTACK)
        doc2 = _scan(FULLSTACK)
        assert doc1.statistics.total_nodes == doc2.statistics.total_nodes


# ---------------------------------------------------------------------------
# Self-scan: Constrictor analyses its own source tree
# ---------------------------------------------------------------------------

class TestSelfScan:
    @pytest.fixture(scope="class")
    def doc(self):
        return _scan(SRC_ROOT)

    def test_self_scan_succeeds(self, doc):
        assert isinstance(doc, GraphDocument)

    def test_self_scan_has_nodes(self, doc):
        assert doc.statistics.total_nodes > 10

    def test_self_scan_no_failed_files(self, doc):
        assert doc.statistics.failed_files == 0

    def test_self_scan_deterministic(self):
        doc1 = _scan(SRC_ROOT)
        doc2 = _scan(SRC_ROOT)
        assert {n.id for n in doc1.nodes} == {n.id for n in doc2.nodes}
        assert {e.id for e in doc1.edges} == {e.id for e in doc2.edges}

    def test_self_scan_roundtrip(self):
        original = _scan(SRC_ROOT)
        json1 = export_json(original, pretty=True)
        reloaded = _json_roundtrip(original)
        json2 = export_json(reloaded, pretty=True)
        assert json1 == json2

    def test_self_scan_finds_orchestrator(self, doc):
        """Constrictor should find its own orchestrator module."""
        module_names = {n.name for n in doc.nodes if n.type == NodeType.MODULE}
        assert any("orchestrator" in name for name in module_names)

    def test_self_scan_summary_valid(self, doc):
        from constrictor.export.summary import generate_summary
        summary = generate_summary(doc)
        assert len(summary) > 20
        assert "node" in summary.lower()


# ---------------------------------------------------------------------------
# Cross-project: query engine on real graphs
# ---------------------------------------------------------------------------

class TestQueryEngineOnRealGraphs:
    def test_impact_upstream_on_fastapi(self):
        doc = _scan(FASTAPI)
        engine = GraphQueryEngine(doc)
        # Find any function that exists in the graph
        funcs = [n for n in doc.nodes if n.type in (NodeType.FUNCTION, NodeType.METHOD)]
        assert funcs, "Need function nodes to test impact"
        func = funcs[0]
        subgraph = engine.impact(func.id, direction="upstream", max_depth=4)
        # The focus node itself is not in subgraph.nodes; just ensure it doesn't raise
        assert isinstance(subgraph.nodes, list)

    def test_dependents_by_file_path(self):
        doc = _scan(SIMPLE)
        engine = GraphQueryEngine(doc)
        # utils.py is imported by main.py; dependents should find something
        nodes = engine.dependents("app/utils.py")
        assert isinstance(nodes, list)

    def test_find_paths_on_simple(self):
        doc = _scan(SIMPLE)
        engine = GraphQueryEngine(doc)
        result = engine.find_paths("app.main", "app.utils", max_depth=4)
        # There should be a direct import path
        assert result.paths, "Expected at least one path from app.main to app.utils"

    def test_ambiguous_audit_returns_review(self):
        doc = _scan(SIMPLE)
        engine = GraphQueryEngine(doc)
        review = engine.ambiguous_audit()
        assert isinstance(review.unresolved_edges, list)
        assert isinstance(review.ambiguous_edges, list)
