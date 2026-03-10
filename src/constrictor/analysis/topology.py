from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from constrictor.core.models import Certainty, ScanWarning
from constrictor.core.parser import ParsedModule
from constrictor.graph.builder import GraphBuilder
from constrictor.graph.id_factory import create_id
from constrictor.graph.models import EdgeType, NodeType


def _service_id(name: str) -> str:
    return create_id("svc", name)


def _component_id(name: str) -> str:
    return create_id("comp", name)


def _parse_docker_compose(path: Path) -> dict[str, dict]:
    """Parse a docker-compose.yml and return a mapping of service_name -> service_info.

    service_info keys: 'build_context', 'ports', 'command', 'dockerfile'
    """
    try:
        with path.open() as fh:
            data = yaml.safe_load(fh)
    except Exception:
        return {}

    if not isinstance(data, dict):
        return {}

    services_raw = data.get("services") or {}
    if not isinstance(services_raw, dict):
        return {}

    result: dict[str, dict] = {}
    for svc_name, svc_cfg in services_raw.items():
        if not isinstance(svc_cfg, dict):
            continue
        info: dict = {}
        build = svc_cfg.get("build")
        if isinstance(build, str):
            info["build_context"] = build
        elif isinstance(build, dict):
            info["build_context"] = build.get("context", "")
            if "dockerfile" in build:
                info["dockerfile"] = build["dockerfile"]

        ports = svc_cfg.get("ports")
        if isinstance(ports, list):
            info["ports"] = ", ".join(str(p) for p in ports)

        command = svc_cfg.get("command")
        if command is not None:
            info["command"] = str(command)

        result[svc_name] = info

    return result


def _parse_dockerfile_entrypoint(path: Path) -> str:
    """Extract CMD/ENTRYPOINT from a Dockerfile as a plain string."""
    try:
        text = path.read_text(errors="replace")
    except Exception:
        return ""
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.upper().startswith("CMD") or line.upper().startswith("ENTRYPOINT"):
            # Strip the directive keyword
            rest = re.sub(r"^(CMD|ENTRYPOINT)\s*", "", line, flags=re.IGNORECASE).strip()
            return rest
    return ""


def _parse_procfile(path: Path) -> dict[str, str]:
    """Parse a Procfile and return {process_name: command}."""
    result: dict[str, str] = {}
    try:
        text = path.read_text(errors="replace")
    except Exception:
        return result
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            name, _, cmd = line.partition(":")
            result[name.strip()] = cmd.strip()
    return result


def _parse_pyproject_name(path: Path) -> str | None:
    """Extract [project] name from a pyproject.toml."""
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            # Fallback: naive regex
            try:
                text = path.read_text(errors="replace")
            except Exception:
                return None
            m = re.search(r'^\s*\[project\].*?name\s*=\s*"([^"]+)"', text, re.DOTALL | re.MULTILINE)
            return m.group(1) if m else path.parent.name

    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        return data.get("project", {}).get("name") or path.parent.name
    except Exception:
        return path.parent.name


class TopologyContributor:
    """Two-phase contributor that detects service/component topology.

    Phase A (contribute): parses config files, creates SERVICE/COMPONENT nodes.
    Phase B (post_process): tags cross-boundary edges and BELONGS_TO_SERVICE edges.
    """

    name = "topology"

    def __init__(self, config_files: list[Path] | None = None) -> None:
        self._config_files: list[Path] = config_files or []
        # Maps absolute directory prefix (as string) -> service/component node id
        self._dir_to_service: dict[str, str] = {}
        # Maps service node id -> service name (for display)
        self._service_id_to_name: dict[str, str] = {}

    def contribute(
        self,
        parsed_modules: list[ParsedModule],
        builder: GraphBuilder,
        warnings: list[ScanWarning],
    ) -> None:
        """Phase A: read config files and create SERVICE/COMPONENT nodes."""
        docker_compose_files: list[Path] = []
        pyproject_files: list[Path] = []
        dockerfile_files: list[Path] = []
        procfile_files: list[Path] = []

        for cfg in self._config_files:
            name_lower = cfg.name.lower()
            if name_lower in ("docker-compose.yml", "docker-compose.yaml"):
                docker_compose_files.append(cfg)
            elif cfg.name == "pyproject.toml":
                pyproject_files.append(cfg)
            elif name_lower == "dockerfile":
                dockerfile_files.append(cfg)
            elif cfg.name == "Procfile":
                procfile_files.append(cfg)

        # --- docker-compose.yml ---
        for dc_path in docker_compose_files:
            services = _parse_docker_compose(dc_path)
            for svc_name, info in services.items():
                build_ctx = info.get("build_context", "")
                if build_ctx:
                    ctx_path = (dc_path.parent / build_ctx).resolve()
                else:
                    ctx_path = dc_path.parent.resolve()

                svc_id = _service_id(svc_name)

                metadata: dict[str, str] = {"source": str(dc_path)}
                if info.get("ports"):
                    metadata["ports"] = info["ports"]
                if info.get("command"):
                    metadata["command"] = info["command"]
                if info.get("dockerfile"):
                    metadata["dockerfile"] = info["dockerfile"]
                if build_ctx:
                    metadata["build_context"] = build_ctx

                # Check if there is a Dockerfile for this context to get entrypoint
                df_path = ctx_path / (info.get("dockerfile") or "Dockerfile")
                if df_path.exists():
                    ep = _parse_dockerfile_entrypoint(df_path)
                    if ep:
                        metadata["entrypoint"] = ep

                builder.add_node(
                    id=svc_id,
                    type=NodeType.SERVICE,
                    name=svc_name,
                    qualified_name=svc_name,
                    display_name=svc_name,
                    file_path=str(dc_path),
                    certainty=Certainty.EXACT,
                    metadata=metadata,
                )
                self._dir_to_service[str(ctx_path)] = svc_id
                self._service_id_to_name[svc_id] = svc_name

        # --- Procfile ---
        for pf_path in procfile_files:
            processes = _parse_procfile(pf_path)
            for proc_name, cmd in processes.items():
                svc_id = _service_id(proc_name)
                metadata = {"source": str(pf_path), "command": cmd}

                # Try to infer directory from command path
                # e.g. "web: python backend/app.py" -> backend/
                ctx_path = pf_path.parent.resolve()
                cmd_parts = cmd.split()
                for part in cmd_parts:
                    candidate = (pf_path.parent / part).resolve()
                    if candidate.is_dir():
                        ctx_path = candidate
                        break
                    # e.g. "backend/app.py" -> parent is backend/
                    if "/" in part:
                        candidate_dir = (pf_path.parent / Path(part).parent).resolve()
                        if candidate_dir.is_dir():
                            ctx_path = candidate_dir
                            break

                builder.add_node(
                    id=svc_id,
                    type=NodeType.SERVICE,
                    name=proc_name,
                    qualified_name=proc_name,
                    display_name=proc_name,
                    file_path=str(pf_path),
                    certainty=Certainty.INFERRED,
                    metadata=metadata,
                )
                self._dir_to_service[str(ctx_path)] = svc_id
                self._service_id_to_name[svc_id] = proc_name

        # --- Multiple pyproject.toml files -> COMPONENT nodes ---
        # Only if more than one (single pyproject at root is not treated as a component boundary)
        if len(pyproject_files) > 1:
            for pp_path in pyproject_files:
                comp_name = _parse_pyproject_name(pp_path) or pp_path.parent.name
                ctx_path = pp_path.parent.resolve()

                # If this directory is already covered by a SERVICE node from docker-compose,
                # upgrade the existing node rather than creating a duplicate COMPONENT.
                svc_id_existing = self._dir_to_service.get(str(ctx_path))
                if svc_id_existing is not None:
                    # Already tracked as a service, just record the package name
                    builder.add_node(
                        id=svc_id_existing,
                        type=NodeType.SERVICE,
                        name=self._service_id_to_name.get(svc_id_existing, comp_name),
                        qualified_name=self._service_id_to_name.get(svc_id_existing, comp_name),
                        display_name=self._service_id_to_name.get(svc_id_existing, comp_name),
                        metadata={"package_name": comp_name},
                    )
                    continue

                comp_id = _component_id(comp_name)
                builder.add_node(
                    id=comp_id,
                    type=NodeType.COMPONENT,
                    name=comp_name,
                    qualified_name=comp_name,
                    display_name=comp_name,
                    file_path=str(pp_path),
                    certainty=Certainty.EXACT,
                    metadata={"source": str(pp_path)},
                )
                self._dir_to_service[str(ctx_path)] = comp_id
                self._service_id_to_name[comp_id] = comp_name

    def post_process(self, builder: GraphBuilder) -> None:
        """Phase B: tag cross-boundary edges and emit BELONGS_TO_SERVICE edges."""
        if not self._dir_to_service:
            return

        # Build a sorted list of (dir_prefix, service_id) so longest match wins
        sorted_dirs = sorted(self._dir_to_service.keys(), key=len, reverse=True)

        def _find_service(file_path: str | None) -> str | None:
            if not file_path:
                return None
            abs_fp = str(Path(file_path).resolve())
            for prefix in sorted_dirs:
                if abs_fp == prefix or abs_fp.startswith(prefix + "/"):
                    return self._dir_to_service[prefix]
            return None

        # BELONGS_TO_SERVICE: link each module/package node to its owning service
        for node in list(builder._nodes.values()):
            if node.type not in (NodeType.MODULE, NodeType.PACKAGE):
                continue
            svc_id = _find_service(node.file_path)
            if svc_id is None:
                continue
            builder.add_edge(
                source_id=node.id,
                target_id=svc_id,
                type=EdgeType.BELONGS_TO_SERVICE,
                display_name=f"{node.display_name} belongs to {self._service_id_to_name.get(svc_id, svc_id)}",
                file_path=node.file_path,
                certainty=Certainty.EXACT,
            )

        # CROSSES_COMPONENT_BOUNDARY: tag existing edges that span services
        for edge in list(builder._edges.values()):
            src_node = builder._nodes.get(edge.source_id)
            tgt_node = builder._nodes.get(edge.target_id)
            if src_node is None or tgt_node is None:
                continue
            src_svc = _find_service(src_node.file_path)
            tgt_svc = _find_service(tgt_node.file_path)
            if src_svc is None or tgt_svc is None:
                continue
            if src_svc == tgt_svc:
                continue
            src_name = self._service_id_to_name.get(src_svc, src_svc)
            tgt_name = self._service_id_to_name.get(tgt_svc, tgt_svc)
            # Add a dedicated CROSSES_COMPONENT_BOUNDARY edge between the two service nodes
            builder.add_edge(
                source_id=edge.source_id,
                target_id=edge.target_id,
                type=EdgeType.CROSSES_COMPONENT_BOUNDARY,
                display_name=(
                        f"{src_node.display_name} -> {tgt_node.display_name}"
                        f" [cross-boundary: {src_name} -> {tgt_name}]"
                    ),
                file_path=edge.file_path,
                line_number=edge.line_number,
                certainty=edge.certainty,
                metadata={"from_service": src_name, "to_service": tgt_name},
            )

        # API contract surface: collect ENDPOINT nodes per service and embed in service metadata
        service_endpoints: dict[str, list[str]] = {}
        for node in builder._nodes.values():
            if node.type != NodeType.ENDPOINT:
                continue
            svc_id = _find_service(node.file_path)
            if svc_id is None:
                continue
            service_endpoints.setdefault(svc_id, []).append(node.display_name)

        for svc_id, endpoints in service_endpoints.items():
            svc_node = builder._nodes.get(svc_id)
            if svc_node is None:
                continue
            builder.add_node(
                id=svc_id,
                type=svc_node.type,
                name=svc_node.name,
                qualified_name=svc_node.qualified_name,
                display_name=svc_node.display_name,
                file_path=svc_node.file_path,
                metadata={"endpoints": json.dumps(sorted(endpoints))},
            )
