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
        self._hashes_path.write_text(
            json.dumps(self._hashes, sort_keys=True, indent=2), encoding="utf-8"
        )

    # ------------------------------------------------------------------ diff

    def diff(self, current_files: list[Path]) -> DiffResult:
        """Compare `current_files` against the cached hashes and return a DiffResult."""
        if not self._loaded:
            self.load()

        current_map: dict[str, str] = {
            str(p.resolve()): hash_file(p) for p in current_files
        }
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
