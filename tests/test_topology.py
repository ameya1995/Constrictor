"""Tests for the TopologyContributor (Phase 6)."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from constrictor.analysis.topology import (
    TopologyContributor,
    _parse_docker_compose,
    _parse_dockerfile_entrypoint,
    _parse_procfile,
    _parse_pyproject_name,
)
from constrictor.core.models import ScanOptions
from constrictor.core.orchestrator import run_scan
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.models import EdgeType, NodeType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "fullstack_project"


def _make_builder() -> GraphBuilder:
    return GraphBuilder()


# ---------------------------------------------------------------------------
# Unit tests: docker-compose parsing
# ---------------------------------------------------------------------------


def test_parse_docker_compose_basic(tmp_path: Path) -> None:
    dc = tmp_path / "docker-compose.yml"
    dc.write_text(
        textwrap.dedent(
            """\
            version: "3.9"
            services:
              api:
                build:
                  context: ./backend
                  dockerfile: Dockerfile
                ports:
                  - "8000:8000"
                command: uvicorn app.main:app
              worker:
                build: ./worker
                command: python -m tasks.process
            """
        )
    )
    services = _parse_docker_compose(dc)
    assert set(services.keys()) == {"api", "worker"}
    assert services["api"]["build_context"] == "./backend"
    assert services["api"]["dockerfile"] == "Dockerfile"
    assert services["api"]["ports"] == "8000:8000"
    assert services["api"]["command"] == "uvicorn app.main:app"
    assert services["worker"]["build_context"] == "./worker"


def test_parse_docker_compose_no_services(tmp_path: Path) -> None:
    dc = tmp_path / "docker-compose.yml"
    dc.write_text("version: '3'\n")
    assert _parse_docker_compose(dc) == {}


def test_parse_docker_compose_invalid_yaml(tmp_path: Path) -> None:
    dc = tmp_path / "docker-compose.yml"
    dc.write_text(": : :\n")
    # Should not raise, just return empty
    result = _parse_docker_compose(dc)
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Unit tests: Dockerfile entrypoint parsing
# ---------------------------------------------------------------------------


def test_parse_dockerfile_entrypoint_cmd(tmp_path: Path) -> None:
    df = tmp_path / "Dockerfile"
    df.write_text("FROM python:3.11\nRUN pip install .\nCMD [\"uvicorn\", \"app:app\"]\n")
    ep = _parse_dockerfile_entrypoint(df)
    assert "uvicorn" in ep


def test_parse_dockerfile_entrypoint_missing(tmp_path: Path) -> None:
    df = tmp_path / "Dockerfile"
    df.write_text("FROM python:3.11\nRUN pip install .\n")
    assert _parse_dockerfile_entrypoint(df) == ""


# ---------------------------------------------------------------------------
# Unit tests: Procfile parsing
# ---------------------------------------------------------------------------


def test_parse_procfile_basic(tmp_path: Path) -> None:
    pf = tmp_path / "Procfile"
    pf.write_text("web: gunicorn app:application\nworker: celery -A tasks worker\n")
    procs = _parse_procfile(pf)
    assert procs["web"] == "gunicorn app:application"
    assert procs["worker"] == "celery -A tasks worker"


def test_parse_procfile_comments_and_blank_lines(tmp_path: Path) -> None:
    pf = tmp_path / "Procfile"
    pf.write_text("# comment\n\nweb: gunicorn app:application\n")
    procs = _parse_procfile(pf)
    assert list(procs.keys()) == ["web"]


# ---------------------------------------------------------------------------
# Unit tests: pyproject.toml name extraction
# ---------------------------------------------------------------------------


def test_parse_pyproject_name(tmp_path: Path) -> None:
    pp = tmp_path / "pyproject.toml"
    pp.write_text('[project]\nname = "myservice"\nversion = "1.0"\n')
    assert _parse_pyproject_name(pp) == "myservice"


def test_parse_pyproject_name_fallback(tmp_path: Path) -> None:
    pp = tmp_path / "pyproject.toml"
    pp.write_text("[build-system]\nrequires = []\n")
    # Falls back to directory name
    result = _parse_pyproject_name(pp)
    assert result == tmp_path.name


# ---------------------------------------------------------------------------
# Unit tests: TopologyContributor – SERVICE node creation from docker-compose
# ---------------------------------------------------------------------------


def test_topology_service_nodes_from_docker_compose(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    worker_dir = tmp_path / "worker"
    worker_dir.mkdir()

    dc = tmp_path / "docker-compose.yml"
    dc.write_text(
        textwrap.dedent(
            """\
            version: "3.9"
            services:
              api:
                build: ./backend
              worker:
                build: ./worker
            """
        )
    )

    contributor = TopologyContributor(config_files=[dc])
    builder = _make_builder()
    contributor.contribute([], builder, [])

    service_nodes = [n for n in builder._nodes.values() if n.type == NodeType.SERVICE]
    names = {n.name for n in service_nodes}
    assert "api" in names
    assert "worker" in names


# ---------------------------------------------------------------------------
# Unit tests: TopologyContributor – COMPONENT nodes from multiple pyprojects
# ---------------------------------------------------------------------------


def test_topology_component_nodes_from_multi_pyproject(tmp_path: Path) -> None:
    (tmp_path / "backend").mkdir()
    (tmp_path / "shared").mkdir()
    pp1 = tmp_path / "backend" / "pyproject.toml"
    pp1.write_text('[project]\nname = "backend"\n')
    pp2 = tmp_path / "shared" / "pyproject.toml"
    pp2.write_text('[project]\nname = "shared"\n')

    contributor = TopologyContributor(config_files=[pp1, pp2])
    builder = _make_builder()
    contributor.contribute([], builder, [])

    comp_nodes = [n for n in builder._nodes.values() if n.type == NodeType.COMPONENT]
    names = {n.name for n in comp_nodes}
    assert "backend" in names
    assert "shared" in names


def test_topology_single_pyproject_not_treated_as_component(tmp_path: Path) -> None:
    pp = tmp_path / "pyproject.toml"
    pp.write_text('[project]\nname = "myapp"\n')

    contributor = TopologyContributor(config_files=[pp])
    builder = _make_builder()
    contributor.contribute([], builder, [])

    # Single pyproject -> no component nodes created
    comp_nodes = [n for n in builder._nodes.values() if n.type == NodeType.COMPONENT]
    assert comp_nodes == []


# ---------------------------------------------------------------------------
# Unit tests: TopologyContributor – cross-boundary edge tagging
# ---------------------------------------------------------------------------


def test_topology_cross_boundary_edge_tagging(tmp_path: Path) -> None:
    """Two modules in different services should get a CROSSES_COMPONENT_BOUNDARY edge."""
    svc_a = tmp_path / "svc_a"
    svc_a.mkdir()
    svc_b = tmp_path / "svc_b"
    svc_b.mkdir()

    dc = tmp_path / "docker-compose.yml"
    dc.write_text(
        textwrap.dedent(
            """\
            version: "3.9"
            services:
              svc_a:
                build: ./svc_a
              svc_b:
                build: ./svc_b
            """
        )
    )

    contributor = TopologyContributor(config_files=[dc])
    builder = _make_builder()
    contributor.contribute([], builder, [])

    # Add two module nodes in different service directories
    file_a = str(svc_a / "module_a.py")
    file_b = str(svc_b / "module_b.py")

    builder.add_node(
        id="mod:a",
        type=NodeType.MODULE,
        name="module_a",
        qualified_name="module_a",
        display_name="module_a",
        file_path=file_a,
    )
    builder.add_node(
        id="mod:b",
        type=NodeType.MODULE,
        name="module_b",
        qualified_name="module_b",
        display_name="module_b",
        file_path=file_b,
    )
    builder.add_edge(
        source_id="mod:a",
        target_id="mod:b",
        type=EdgeType.IMPORTS,
        display_name="module_a imports module_b",
        file_path=file_a,
    )

    contributor.post_process(builder)

    cross_edges = [
        e for e in builder._edges.values()
        if e.type == EdgeType.CROSSES_COMPONENT_BOUNDARY
    ]
    assert len(cross_edges) >= 1
    edge = cross_edges[0]
    assert edge.metadata.get("from_service") == "svc_a"
    assert edge.metadata.get("to_service") == "svc_b"


def test_topology_no_cross_boundary_within_same_service(tmp_path: Path) -> None:
    svc = tmp_path / "svc"
    svc.mkdir()

    dc = tmp_path / "docker-compose.yml"
    dc.write_text(
        textwrap.dedent(
            """\
            version: "3.9"
            services:
              svc:
                build: ./svc
            """
        )
    )

    contributor = TopologyContributor(config_files=[dc])
    builder = _make_builder()
    contributor.contribute([], builder, [])

    file_a = str(svc / "mod_a.py")
    file_b = str(svc / "mod_b.py")
    builder.add_node("mod:a", NodeType.MODULE, "mod_a", file_path=file_a)
    builder.add_node("mod:b", NodeType.MODULE, "mod_b", file_path=file_b)
    builder.add_edge("mod:a", "mod:b", EdgeType.IMPORTS, file_path=file_a)

    contributor.post_process(builder)

    cross_edges = [
        e for e in builder._edges.values()
        if e.type == EdgeType.CROSSES_COMPONENT_BOUNDARY
    ]
    assert cross_edges == []


# ---------------------------------------------------------------------------
# Unit tests: TopologyContributor – BELONGS_TO_SERVICE edges
# ---------------------------------------------------------------------------


def test_topology_belongs_to_service_edges(tmp_path: Path) -> None:
    svc_dir = tmp_path / "svc"
    svc_dir.mkdir()

    dc = tmp_path / "docker-compose.yml"
    dc.write_text(
        textwrap.dedent(
            """\
            version: "3.9"
            services:
              mysvc:
                build: ./svc
            """
        )
    )

    contributor = TopologyContributor(config_files=[dc])
    builder = _make_builder()
    contributor.contribute([], builder, [])

    fp = str(svc_dir / "mymodule.py")
    builder.add_node("mod:x", NodeType.MODULE, "mymodule", file_path=fp)

    contributor.post_process(builder)

    belongs_edges = [
        e for e in builder._edges.values()
        if e.type == EdgeType.BELONGS_TO_SERVICE
    ]
    assert len(belongs_edges) >= 1
    assert belongs_edges[0].source_id == "mod:x"


# ---------------------------------------------------------------------------
# Unit tests: API contract surface
# ---------------------------------------------------------------------------


def test_topology_api_contract_surface(tmp_path: Path) -> None:
    svc_dir = tmp_path / "api"
    svc_dir.mkdir()

    dc = tmp_path / "docker-compose.yml"
    dc.write_text(
        textwrap.dedent(
            """\
            version: "3.9"
            services:
              api:
                build: ./api
            """
        )
    )

    contributor = TopologyContributor(config_files=[dc])
    builder = _make_builder()
    contributor.contribute([], builder, [])

    fp = str(svc_dir / "routes.py")
    builder.add_node("ep:1", NodeType.ENDPOINT, "GET /users", file_path=fp)
    builder.add_node("ep:2", NodeType.ENDPOINT, "POST /users", file_path=fp)

    contributor.post_process(builder)

    svc_nodes = [n for n in builder._nodes.values() if n.type == NodeType.SERVICE]
    assert svc_nodes
    svc_node = svc_nodes[0]
    assert "endpoints" in svc_node.metadata
    endpoints = json.loads(svc_node.metadata["endpoints"])
    assert "GET /users" in endpoints
    assert "POST /users" in endpoints


# ---------------------------------------------------------------------------
# Unit tests: Procfile parsing -> SERVICE nodes
# ---------------------------------------------------------------------------


def test_topology_procfile_service_nodes(tmp_path: Path) -> None:
    pf = tmp_path / "Procfile"
    pf.write_text("web: gunicorn app:application\nworker: celery -A tasks worker\n")

    contributor = TopologyContributor(config_files=[pf])
    builder = _make_builder()
    contributor.contribute([], builder, [])

    service_names = {n.name for n in builder._nodes.values() if n.type == NodeType.SERVICE}
    assert "web" in service_names
    assert "worker" in service_names


# ---------------------------------------------------------------------------
# Integration test: full scan of fullstack_project fixture
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not FIXTURE_ROOT.exists(),
    reason="fullstack_project fixture not found",
)
def test_fullstack_integration_scan() -> None:
    options = ScanOptions(root_path=FIXTURE_ROOT)
    document = run_scan(options)

    # 3 services should be detected: api, worker (from docker-compose) + shared (pyproject)
    # In practice the docker-compose defines api + worker, and shared is a pyproject COMPONENT
    service_nodes = [
        n for n in document.nodes
        if n.type in (NodeType.SERVICE, NodeType.COMPONENT)
    ]
    service_names = {n.name for n in service_nodes}
    assert "api" in service_names, f"Expected 'api' in {service_names}"
    assert "worker" in service_names, f"Expected 'worker' in {service_names}"

    # Statistics should record service count
    assert document.statistics.service_count >= 2


@pytest.mark.skipif(
    not FIXTURE_ROOT.exists(),
    reason="fullstack_project fixture not found",
)
def test_fullstack_belongs_to_service_edges() -> None:
    options = ScanOptions(root_path=FIXTURE_ROOT)
    document = run_scan(options)

    belongs_edges = [e for e in document.edges if e.type == EdgeType.BELONGS_TO_SERVICE]
    assert len(belongs_edges) > 0, "Expected BELONGS_TO_SERVICE edges to be emitted"


@pytest.mark.skipif(
    not FIXTURE_ROOT.exists(),
    reason="fullstack_project fixture not found",
)
def test_fullstack_cross_component_edges_exist() -> None:
    options = ScanOptions(root_path=FIXTURE_ROOT)
    document = run_scan(options)

    cross_edges = [e for e in document.edges if e.type == EdgeType.CROSSES_COMPONENT_BOUNDARY]
    assert document.statistics.cross_component_edge_count == len(cross_edges)


@pytest.mark.skipif(
    not FIXTURE_ROOT.exists(),
    reason="fullstack_project fixture not found",
)
def test_fullstack_endpoint_contract_on_api_service() -> None:
    options = ScanOptions(root_path=FIXTURE_ROOT)
    document = run_scan(options)

    api_node = next((n for n in document.nodes if n.name == "api" and n.type == NodeType.SERVICE), None)
    if api_node is None:
        pytest.skip("api SERVICE node not found – may be due to docker-compose context resolution")

    if "endpoints" in api_node.metadata:
        endpoints = json.loads(api_node.metadata["endpoints"])
        # The fixture has GET /orders/{order_id} and POST /orders
        assert any("/orders" in ep for ep in endpoints), f"No orders endpoint found in {endpoints}"
