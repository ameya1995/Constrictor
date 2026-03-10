from __future__ import annotations

from datetime import datetime
from enum import IntEnum
from pathlib import Path

from pydantic import BaseModel


class Certainty(IntEnum):
    UNRESOLVED = 0
    AMBIGUOUS = 1
    INFERRED = 2
    EXACT = 3


class SourceLocation(BaseModel):
    file_path: str
    line: int | None = None
    column: int | None = None


class ScanOptions(BaseModel):
    root_path: Path
    max_depth: int = 64
    exclude_patterns: list[str] = []
    exclude_files: list[Path] = []
    include_tests: bool = False
    include_js: bool = False


class ScanWarning(BaseModel):
    code: str
    message: str
    path: str | None = None
    certainty: Certainty = Certainty.UNRESOLVED


class StageTiming(BaseModel):
    stage: str
    elapsed_seconds: float


class ScanMetadata(BaseModel):
    root_path: str
    started_at: datetime
    completed_at: datetime
    python_version: str
    constrictor_version: str
    timings: list[StageTiming] = []


class ScanStatistics(BaseModel):
    total_files: int = 0
    parsed_files: int = 0
    failed_files: int = 0
    total_nodes: int = 0
    total_edges: int = 0
    node_type_counts: dict[str, int] = {}
    edge_type_counts: dict[str, int] = {}
    warning_count: int = 0
    service_count: int = 0
    cross_component_edge_count: int = 0
