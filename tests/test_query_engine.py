from __future__ import annotations

import pytest

from constrictor.core.models import Certainty, ScanStatistics
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.models import EdgeType, GraphDocument, NodeType
from constrictor.graph.query import GraphQueryEngine, NodeNotFoundError


def _make_document() -> GraphDocument:
    """Build a small, known graph for testing.

    Structure:
        mod_a --[IMPORTS]--> mod_b
        mod_b --[IMPORTS]--> mod_c
        func_a --[CALLS]--> func_b  (AMBIGUOUS)
        func_b --[CALLS]--> func_c
        mod_a --[CONTAINS]--> func_a
        mod_b --[CONTAINS]--> func_b
        mod_c --[CONTAINS]--> func_c
    """
    builder = GraphBuilder()

    builder.add_node(
        "mod:a", NodeType.MODULE, "app.main",
        qualified_name="app.main", display_name="app.main",
        file_path="app/main.py",
    )
    builder.add_node(
        "mod:b", NodeType.MODULE, "app.utils",
        qualified_name="app.utils", display_name="app.utils",
        file_path="app/utils.py",
    )
    builder.add_node(
        "mod:c", NodeType.MODULE, "app.models",
        qualified_name="app.models", display_name="app.models",
        file_path="app/models.py",
    )
    builder.add_node(
        "func:a", NodeType.FUNCTION, "run_app",
        qualified_name="app.main::run_app", display_name="app.main::run_app",
        file_path="app/main.py",
    )
    builder.add_node(
        "func:b", NodeType.FUNCTION, "greet",
        qualified_name="app.utils::greet", display_name="app.utils::greet",
        file_path="app/utils.py",
    )
    builder.add_node(
        "func:c", NodeType.FUNCTION, "helper",
        qualified_name="app.models::helper", display_name="app.models::helper",
        file_path="app/models.py",
    )

    builder.add_edge("mod:a", "mod:b", EdgeType.IMPORTS, "main -> utils")
    builder.add_edge("mod:b", "mod:c", EdgeType.IMPORTS, "utils -> models")
    builder.add_edge("func:a", "func:b", EdgeType.CALLS, "run_app -> greet", certainty=Certainty.AMBIGUOUS)
    builder.add_edge("func:b", "func:c", EdgeType.CALLS, "greet -> helper")
    builder.add_edge("mod:a", "func:a", EdgeType.CONTAINS, "main contains run_app")
    builder.add_edge("mod:b", "func:b", EdgeType.CONTAINS, "utils contains greet")
    builder.add_edge("mod:c", "func:c", EdgeType.CONTAINS, "models contains helper")

    unresolved_builder = GraphBuilder()
    unresolved_builder.add_node("mod:x", NodeType.EXTERNAL_MODULE, "external",
                                qualified_name="external", display_name="external")
    unresolved_builder.add_edge(
        "mod:a", "mod:x", EdgeType.IMPORTS, "main -> external",
        certainty=Certainty.UNRESOLVED,
    )

    for node in unresolved_builder._nodes.values():
        builder._nodes[node.id] = node
    for edge in unresolved_builder._edges.values():
        builder._edges[edge.id] = edge

    return builder.build()


@pytest.fixture()
def engine() -> GraphQueryEngine:
    return GraphQueryEngine(_make_document())


class TestResolveNode:
    def test_exact_id(self, engine: GraphQueryEngine) -> None:
        node = engine.resolve_node("mod:a")
        assert node.id == "mod:a"

    def test_display_name_exact(self, engine: GraphQueryEngine) -> None:
        node = engine.resolve_node("app.utils")
        assert node.id == "mod:b"

    def test_display_name_case_insensitive(self, engine: GraphQueryEngine) -> None:
        node = engine.resolve_node("APP.UTILS")
        assert node.id == "mod:b"

    def test_qualified_name_contains(self, engine: GraphQueryEngine) -> None:
        node = engine.resolve_node("app.utils::greet")
        assert node.id == "func:b"

    def test_display_name_fuzzy(self, engine: GraphQueryEngine) -> None:
        node = engine.resolve_node("greet")
        assert node.id == "func:b"

    def test_not_found_raises(self, engine: GraphQueryEngine) -> None:
        with pytest.raises(NodeNotFoundError):
            engine.resolve_node("nonexistent_xyz_123")


class TestImpactDownstream:
    def test_downstream_direct(self, engine: GraphQueryEngine) -> None:
        subgraph = engine.impact("mod:a", direction="downstream", max_depth=1)
        ids = {n.id for n in subgraph.nodes}
        assert "mod:b" in ids
        assert "func:a" in ids

    def test_downstream_full_chain(self, engine: GraphQueryEngine) -> None:
        subgraph = engine.impact("mod:a", direction="downstream", max_depth=6)
        ids = {n.id for n in subgraph.nodes}
        assert "mod:b" in ids
        assert "mod:c" in ids

    def test_downstream_max_depth_zero_returns_empty(self, engine: GraphQueryEngine) -> None:
        subgraph = engine.impact("mod:a", direction="downstream", max_depth=0)
        assert subgraph.nodes == []
        assert subgraph.edges == []

    def test_downstream_focus_node_not_in_nodes(self, engine: GraphQueryEngine) -> None:
        subgraph = engine.impact("mod:a", direction="downstream")
        ids = {n.id for n in subgraph.nodes}
        assert "mod:a" not in ids
        assert subgraph.focus_node.id == "mod:a"


class TestImpactUpstream:
    def test_upstream_finds_callers(self, engine: GraphQueryEngine) -> None:
        subgraph = engine.impact("func:b", direction="upstream")
        ids = {n.id for n in subgraph.nodes}
        assert "func:a" in ids

    def test_upstream_finds_module_import(self, engine: GraphQueryEngine) -> None:
        subgraph = engine.impact("mod:b", direction="upstream")
        ids = {n.id for n in subgraph.nodes}
        assert "mod:a" in ids

    def test_upstream_leaf_has_only_container(self, engine: GraphQueryEngine) -> None:
        # func:a is contained by mod:a (CONTAINS edge), so mod:a is upstream of func:a
        subgraph = engine.impact("func:a", direction="upstream")
        ids = {n.id for n in subgraph.nodes}
        assert "mod:a" in ids
        # func:b should not appear (func:a doesn't depend on func:b upstream)
        assert "func:b" not in ids


class TestImpactAmbiguous:
    def test_exclude_ambiguous_skips_edges(self, engine: GraphQueryEngine) -> None:
        subgraph = engine.impact("func:a", direction="downstream", include_ambiguous=False)
        ids = {n.id for n in subgraph.nodes}
        assert "func:b" not in ids

    def test_include_ambiguous_traverses_edge(self, engine: GraphQueryEngine) -> None:
        subgraph = engine.impact("func:a", direction="downstream", include_ambiguous=True)
        ids = {n.id for n in subgraph.nodes}
        assert "func:b" in ids


class TestFindPaths:
    def test_direct_path(self, engine: GraphQueryEngine) -> None:
        result = engine.find_paths("mod:a", "mod:b")
        assert len(result.paths) >= 1
        first_path = result.paths[0]
        assert first_path.nodes[0].id == "mod:a"
        assert first_path.nodes[-1].id == "mod:b"

    def test_multi_hop_path(self, engine: GraphQueryEngine) -> None:
        result = engine.find_paths("mod:a", "mod:c")
        assert len(result.paths) >= 1
        path_node_ids = [n.id for n in result.paths[0].nodes]
        assert "mod:a" in path_node_ids
        assert "mod:c" in path_node_ids

    def test_no_path_returns_empty(self, engine: GraphQueryEngine) -> None:
        result = engine.find_paths("mod:c", "mod:a")
        assert result.paths == []

    def test_from_and_to_nodes_set(self, engine: GraphQueryEngine) -> None:
        result = engine.find_paths("mod:a", "func:c")
        assert result.from_node.id == "mod:a"
        assert result.to_node.id == "func:c"

    def test_not_found_raises(self, engine: GraphQueryEngine) -> None:
        with pytest.raises(NodeNotFoundError):
            engine.find_paths("mod:a", "nonexistent_xyz")


class TestAmbiguousAudit:
    def test_collects_ambiguous_edges(self, engine: GraphQueryEngine) -> None:
        review = engine.ambiguous_audit()
        ambiguous_ids = {e.id for e in review.ambiguous_edges}
        assert any(True for e in engine._document.edges if e.certainty == Certainty.AMBIGUOUS and e.id in ambiguous_ids)

    def test_collects_unresolved_edges(self, engine: GraphQueryEngine) -> None:
        review = engine.ambiguous_audit()
        assert len(review.unresolved_edges) >= 1

    def test_sorted_by_type_then_name(self, engine: GraphQueryEngine) -> None:
        review = engine.ambiguous_audit()
        for lst in (review.ambiguous_edges, review.unresolved_edges):
            keys = [(e.type.value, e.display_name) for e in lst]
            assert keys == sorted(keys)

    def test_exact_edges_not_included(self, engine: GraphQueryEngine) -> None:
        review = engine.ambiguous_audit()
        all_flagged = set(e.id for e in review.ambiguous_edges) | set(e.id for e in review.unresolved_edges)
        for edge in engine._document.edges:
            if edge.certainty == Certainty.EXACT:
                assert edge.id not in all_flagged


class TestDependents:
    def test_dependents_of_file(self, engine: GraphQueryEngine) -> None:
        deps = engine.dependents("app/utils.py")
        dep_ids = {n.id for n in deps}
        assert "func:a" in dep_ids or "mod:a" in dep_ids

    def test_dependents_of_nonexistent_file_returns_empty(self, engine: GraphQueryEngine) -> None:
        deps = engine.dependents("app/no_such_file.py")
        assert deps == []

    def test_dependents_no_duplicates(self, engine: GraphQueryEngine) -> None:
        deps = engine.dependents("app/utils.py")
        ids = [n.id for n in deps]
        assert len(ids) == len(set(ids))
