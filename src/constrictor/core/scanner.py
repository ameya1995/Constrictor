from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel

from constrictor.core.ignore import load_ignore_patterns, should_exclude
from constrictor.core.models import Certainty, ScanOptions, ScanWarning

_TOPOLOGY_CONFIG_NAMES = frozenset(
    [
        "docker-compose.yml",
        "docker-compose.yaml",
        "Dockerfile",
        "Procfile",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
    ]
)


_JS_EXTENSIONS = frozenset([".js", ".ts", ".jsx", ".tsx"])


class ScanResult(BaseModel):
    python_files: list[Path]
    js_files: list[Path] = []
    config_files: list[Path]
    warnings: list[ScanWarning]

    model_config = {"arbitrary_types_allowed": True}


def scan_directory(options: ScanOptions) -> ScanResult:
    patterns = load_ignore_patterns(
        options.root_path,
        extra_exclude_files=options.exclude_files if options.exclude_files else None,
        extra_patterns=options.exclude_patterns if options.exclude_patterns else None,
    )

    python_files: list[Path] = []
    js_files: list[Path] = []
    config_files: list[Path] = []
    warnings: list[ScanWarning] = []
    visited_real_paths: set[str] = set()

    root = options.root_path.resolve()

    for dirpath_str, dirnames, filenames in os.walk(str(root), followlinks=True):
        dirpath = Path(dirpath_str)

        # Track symlink loops via real paths
        try:
            real_dirpath = str(dirpath.resolve())
        except OSError:
            continue

        if real_dirpath in visited_real_paths:
            warnings.append(
                ScanWarning(
                    code="SYMLINK_LOOP",
                    message=f"Symlink loop detected at {dirpath}",
                    path=str(dirpath),
                    certainty=Certainty.UNRESOLVED,
                )
            )
            dirnames.clear()
            continue
        visited_real_paths.add(real_dirpath)

        # Enforce max_depth
        try:
            depth = len(dirpath.relative_to(root).parts)
        except ValueError:
            depth = 0

        if depth > options.max_depth:
            dirnames.clear()
            continue

        # Filter out excluded directories in-place (modifies os.walk traversal)
        filtered_dirs: list[str] = []
        for d in dirnames:
            dir_path = dirpath / d
            if should_exclude(dir_path, patterns, root=root):
                continue
            filtered_dirs.append(d)
        dirnames[:] = filtered_dirs

        for filename in filenames:
            file_path = dirpath / filename

            if should_exclude(file_path, patterns, root=root):
                continue

            # Check for broken symlinks
            if file_path.is_symlink() and not file_path.exists():
                warnings.append(
                    ScanWarning(
                        code="BROKEN_SYMLINK",
                        message=f"Broken symlink: {file_path}",
                        path=str(file_path),
                        certainty=Certainty.UNRESOLVED,
                    )
                )
                continue

            # Config files take priority; setup.py is a topology config, not a source file
            if filename in _TOPOLOGY_CONFIG_NAMES:
                config_files.append(file_path)
            elif filename.endswith(".py"):
                python_files.append(file_path)
            elif options.include_js and file_path.suffix in _JS_EXTENSIONS:
                js_files.append(file_path)

    return ScanResult(
        python_files=sorted(python_files),
        js_files=sorted(js_files),
        config_files=sorted(config_files),
        warnings=warnings,
    )
