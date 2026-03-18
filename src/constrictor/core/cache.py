"""Incremental scan cache.

Manages `.constrictor_cache/` under the project root. Two things are persisted
per scanned Python file:

  * A SHA-256 content hash (used to detect changes between runs).
  * A "fragment" — the subset of graph nodes and edges that the file contributed
    to the previous full scan result.

On a subsequent scan, `FileCache.diff()` compares current hashes to the stored
ones and buckets every file into one of: unchanged, changed, added, or removed.
The incremental path can then skip re-parsing unchanged files and prune/replace
fragments for changed/added/removed ones.

Config-file changes (.constrictor_ignore, docker-compose.yml, pyproject.toml,
Dockerfile, Procfile) always signal that a full rescan is required; callers
should check `FileCache.config_files_changed()` before taking the incremental
path.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from constrictor.graph.models import GraphEdge, GraphNode

# ---------------------------------------------------------------------------
# Cache directory / file layout
# ---------------------------------------------------------------------------
_CACHE_DIR = ".constrictor_cache"
_HASHES_FILE = "hashes.json"
_FRAGMENTS_DIR = "fragments"

# Config files whose change triggers a mandatory full rescan.
_CONFIG_NAMES = {
    ".constrictor_ignore",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Dockerfile",
    "Procfile",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
}


# ---------------------------------------------------------------------------
# Public data classes
# ---------------------------------------------------------------------------


@dataclass
class FileFragment:
    """Nodes and edges contributed by a single source file in a previous scan."""

    file_path: str
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "nodes": [n.model_dump(mode="json") for n in self.nodes],
            "edges": [e.model_dump(mode="json") for e in self.edges],
        }

    @staticmethod
    def from_dict(data: dict) -> "FileFragment":
        from constrictor.graph.models import GraphEdge, GraphNode

        return FileFragment(
            file_path=data["file_path"],
            nodes=[GraphNode.model_validate(n) for n in data.get("nodes", [])],
            edges=[GraphEdge.model_validate(e) for e in data.get("edges", [])],
        )


@dataclass
class DiffResult:
    """Result of comparing the current file set to the cached state."""

    unchanged: list[Path] = field(default_factory=list)
    changed: list[Path] = field(default_factory=list)
    added: list[Path] = field(default_factory=list)
    removed: list[Path] = field(default_factory=list)

    @property
    def needs_reanalysis(self) -> list[Path]:
        """Files that need to be re-parsed and re-extracted."""
        return self.changed + self.added


# ---------------------------------------------------------------------------
# Hash helpers
# ---------------------------------------------------------------------------


def hash_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file's contents."""
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


# ---------------------------------------------------------------------------
# FileCache
# ---------------------------------------------------------------------------


class FileCache:
    """Persistent cache of per-file hashes and graph fragments."""

    def __init__(self, root_path: Path) -> None:
        self._root = root_path.resolve()
        self._cache_dir = self._root / _CACHE_DIR
        self._hashes_path = self._cache_dir / _HASHES_FILE
        self._fragments_dir = self._cache_dir / _FRAGMENTS_DIR

        # In-memory state loaded lazily (or fresh if no cache exists).
        # Maps str(file_path) -> sha256 hex digest
        self._hashes: dict[str, str] = {}
        self._loaded = False

    # ------------------------------------------------------------------ load/save

    def load(self) -> None:
        """Load persisted hashes from disk. Safe to call even if cache is absent."""
        if self._hashes_path.exists():
            try:
                data = json.loads(self._hashes_path.read_text(encoding="utf-8"))
                self._hashes = data if isinstance(data, dict) else {}
            except (json.JSONDecodeError, OSError):
                self._hashes = {}
        else:
            self._hashes = {}
        self._loaded = True

    def save(self) -> None:
        """Persist the current hash table to disk."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._hashes_path.write_text(json.dumps(self._hashes, sort_keys=True, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------ diff

    def diff(self, current_files: list[Path]) -> DiffResult:
        """Compare `current_files` against the cached hashes and return a DiffResult."""
        if not self._loaded:
            self.load()

        current_map: dict[str, str] = {str(p.resolve()): hash_file(p) for p in current_files}
        prev_keys = set(self._hashes)
        curr_keys = set(current_map)

        result = DiffResult()

        for key in curr_keys - prev_keys:
            result.added.append(Path(key))

        for key in prev_keys - curr_keys:
            result.removed.append(Path(key))

        for key in prev_keys & curr_keys:
            if current_map[key] == self._hashes[key]:
                result.unchanged.append(Path(key))
            else:
                result.changed.append(Path(key))

        return result

    def update_hashes(self, files: list[Path]) -> None:
        """Hash the given files and store the results (call after a successful scan)."""
        if not self._loaded:
            self.load()
        for p in files:
            key = str(p.resolve())
            self._hashes[key] = hash_file(p)

    def remove_hashes(self, files: list[Path]) -> None:
        """Remove hash entries for files that no longer exist."""
        for p in files:
            self._hashes.pop(str(p.resolve()), None)

    # ------------------------------------------------------------------ fragments

    def _fragment_path(self, file_path: Path) -> Path:
        key = str(file_path.resolve())
        digest = hashlib.sha256(key.encode()).hexdigest()[:16]
        return self._fragments_dir / f"{digest}.json"

    def store_fragment(self, fragment: FileFragment) -> None:
        """Persist a FileFragment to disk."""
        self._fragments_dir.mkdir(parents=True, exist_ok=True)
        fp = self._fragment_path(Path(fragment.file_path))
        fp.write_text(json.dumps(fragment.to_dict(), indent=2), encoding="utf-8")

    def load_fragment(self, file_path: Path) -> FileFragment | None:
        """Load a previously stored fragment, or None if not cached."""
        fp = self._fragment_path(file_path)
        if not fp.exists():
            return None
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            return FileFragment.from_dict(data)
        except (json.JSONDecodeError, OSError, KeyError):
            return None

    def delete_fragment(self, file_path: Path) -> None:
        """Remove the fragment for a file (called when a file is removed or changed)."""
        fp = self._fragment_path(file_path)
        if fp.exists():
            try:
                fp.unlink()
            except OSError:
                pass

    def store_fragments(self, fragments: list[FileFragment]) -> None:
        """Batch-store a list of fragments."""
        for frag in fragments:
            self.store_fragment(frag)

    # ------------------------------------------------------------------ config

    def config_files_changed(self, root_path: Path) -> bool:
        """Return True if any config file under root_path differs from its cached hash."""
        if not self._loaded:
            self.load()

        for name in _CONFIG_NAMES:
            candidates = list(root_path.rglob(name))
            for p in candidates:
                key = str(p.resolve())
                current_hash = hash_file(p)
                if key not in self._hashes or self._hashes[key] != current_hash:
                    return True
        return False

    def update_config_hashes(self, root_path: Path) -> None:
        """Hash all config files and update the stored values."""
        if not self._loaded:
            self.load()
        for name in _CONFIG_NAMES:
            for p in root_path.rglob(name):
                self._hashes[str(p.resolve())] = hash_file(p)

    # ------------------------------------------------------------------ validity

    @property
    def is_empty(self) -> bool:
        """True if no hashes have been stored (cache is brand-new or was cleared)."""
        if not self._loaded:
            self.load()
        return len(self._hashes) == 0


# ---------------------------------------------------------------------------
# Staleness checking for agent workflows
# ---------------------------------------------------------------------------


@dataclass
class StalenessResult:
    """Result of checking whether a graph.json is stale relative to source files."""

    is_stale: bool
    """True if any source file changed since the graph was built."""

    graph_path: str
    """Path to the graph.json file that was checked."""

    graph_mtime: float
    """Modification timestamp of graph.json."""

    changed_files: list[Path] = field(default_factory=list)
    """Source files that changed after graph.json was created."""

    added_files: list[Path] = field(default_factory=list)
    """Source files added after graph.json was created."""

    removed_files: list[Path] = field(default_factory=list)
    """Source files removed after graph.json was created."""

    total_scanned_files: int = 0
    """Number of Python files found in the current scan."""

    seconds_since_scan: float = 0.0
    """Seconds elapsed since graph.json was last modified."""

    recommendation: str = ""
    """Human-readable recommendation for the agent."""


def check_graph_staleness(
    graph_path: Path,
    project_root: Path,
    exclude_patterns: list[str] | None = None,
) -> StalenessResult:
    """Check if graph.json is stale relative to the current source files.

    This function compares the modification time of graph.json against all
    Python files in the project. If any source file is newer than the graph,
    the graph is considered stale and should be rebuilt.

    Args:
        graph_path: Path to graph.json
        project_root: Root directory of the project
        exclude_patterns: Optional glob patterns for files to exclude

    Returns:
        StalenessResult with details about what changed and a recommendation.
    """
    import time
    from fnmatch import fnmatch

    if not graph_path.exists():
        return StalenessResult(
            is_stale=True,
            graph_path=str(graph_path),
            graph_mtime=0.0,
            changed_files=[],
            added_files=[],
            removed_files=[],
            recommendation=(f"Graph file not found at {graph_path}. Run 'constrictor scan' to create it."),
        )

    graph_mtime = graph_path.stat().st_mtime
    now = time.time()
    seconds_since = now - graph_mtime

    exclude_patterns = exclude_patterns or []
    default_excludes = {
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        "*.egg-info",
        ".tox",
        ".nox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".constrictor_cache",
    }
    all_excludes = default_excludes.union(set(exclude_patterns))

    def should_exclude(p: Path) -> bool:
        rel = str(p.relative_to(project_root))
        for pattern in all_excludes:
            if fnmatch(rel, pattern) or fnmatch(p.name, pattern):
                return True
            if any(fnmatch(part, pattern) for part in p.parts):
                return True
        return False

    py_files = [p for p in project_root.rglob("*.py") if not should_exclude(p)]

    changed: list[Path] = []
    for p in py_files:
        try:
            if p.stat().st_mtime > graph_mtime:
                changed.append(p)
        except OSError:
            continue

    cache = FileCache(project_root)
    cache.load()
    prev_files = {Path(k) for k in cache._hashes.keys() if k.endswith(".py")}

    current_set = {p.resolve() for p in py_files}
    added = [p for p in current_set if p not in prev_files and p.stat().st_mtime > graph_mtime]
    removed = [p for p in prev_files if p not in current_set]

    is_stale = bool(changed or added or removed)

    if is_stale:
        parts = []
        if changed:
            parts.append(f"{len(changed)} file(s) modified")
        if added:
            parts.append(f"{len(added)} file(s) added")
        if removed:
            parts.append(f"{len(removed)} file(s) removed")

        recommendation = (
            f"Graph is stale: {', '.join(parts)} since last scan. "
            "Call `constrictor_rescan_graph` to update before running impact analysis."
        )
    else:
        if seconds_since > 3600:
            recommendation = (
                f"Graph is {int(seconds_since / 60)} minutes old. Consider rescanning if you've made recent edits."
            )
        else:
            recommendation = "Graph is up-to-date."

    return StalenessResult(
        is_stale=is_stale,
        graph_path=str(graph_path),
        graph_mtime=graph_mtime,
        changed_files=changed,
        added_files=added,
        removed_files=removed,
        total_scanned_files=len(py_files),
        seconds_since_scan=seconds_since,
        recommendation=recommendation,
    )
