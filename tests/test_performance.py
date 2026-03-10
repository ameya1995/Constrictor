"""Performance baseline tests.

These tests are not speed-critical unit tests -- they establish baselines and
guard against severe regressions (e.g. O(n²) behaviour on small inputs).

Thresholds are deliberately generous to avoid flakiness on slow CI machines.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from constrictor.core.models import ScanOptions
from constrictor.core.orchestrator import run_scan
from constrictor.export.json_export import export_json, load_json

SRC_ROOT = Path(__file__).parent.parent / "src" / "constrictor"
SIMPLE = Path(__file__).parent / "fixtures" / "simple_project"
FASTAPI = Path(__file__).parent / "fixtures" / "fastapi_project"
FULLSTACK = Path(__file__).parent / "fixtures" / "fullstack_project"


# ---------------------------------------------------------------------------
# Wall-clock limits (generous: all projects scan well under 1s in practice)
# ---------------------------------------------------------------------------

SELF_SCAN_LIMIT_S = 5.0      # ~38 source files, should complete in <0.5s
FIXTURE_SCAN_LIMIT_S = 3.0   # any single fixture project
LARGE_FILE_PARSE_LIMIT_S = 1.0


class TestScanSpeed:
    def test_self_scan_under_limit(self):
        t0 = time.perf_counter()
        doc = run_scan(ScanOptions(root_path=SRC_ROOT))
        elapsed = time.perf_counter() - t0
        assert elapsed < SELF_SCAN_LIMIT_S, (
            f"Self-scan took {elapsed:.2f}s — expected under {SELF_SCAN_LIMIT_S}s"
        )
        # Sanity: we actually scanned real files
        assert doc.statistics.total_files > 10
        assert doc.statistics.total_nodes > 50

    @pytest.mark.parametrize("fixture_path", [SIMPLE, FASTAPI, FULLSTACK])
    def test_fixture_scan_under_limit(self, fixture_path: Path):
        t0 = time.perf_counter()
        run_scan(ScanOptions(root_path=fixture_path))
        elapsed = time.perf_counter() - t0
        assert elapsed < FIXTURE_SCAN_LIMIT_S, (
            f"Scan of {fixture_path.name} took {elapsed:.2f}s "
            f"— expected under {FIXTURE_SCAN_LIMIT_S}s"
        )

    def test_scan_timing_stages_are_recorded(self):
        doc = run_scan(ScanOptions(root_path=SRC_ROOT))
        assert doc.scan_metadata is not None
        assert doc.scan_metadata.timings
        stage_names = {t.stage for t in doc.scan_metadata.timings}
        assert "scan" in stage_names
        assert "parse" in stage_names
        # At least one extractor stage
        assert any(s.startswith("extract:") for s in stage_names)

    def test_all_stage_timings_are_positive(self):
        doc = run_scan(ScanOptions(root_path=SRC_ROOT))
        if doc.scan_metadata:
            for timing in doc.scan_metadata.timings:
                assert timing.elapsed_seconds >= 0, (
                    f"Stage '{timing.stage}' has negative elapsed time: "
                    f"{timing.elapsed_seconds}"
                )


class TestJsonSerializationSpeed:
    def test_export_json_under_limit(self):
        doc = run_scan(ScanOptions(root_path=SRC_ROOT))
        t0 = time.perf_counter()
        json_str = export_json(doc)
        elapsed = time.perf_counter() - t0
        assert elapsed < 1.0, f"export_json took {elapsed:.3f}s"
        assert len(json_str) > 1000

    def test_load_json_roundtrip_under_limit(self, tmp_path: Path):
        doc = run_scan(ScanOptions(root_path=SRC_ROOT))
        path = tmp_path / "graph.json"
        export_json(doc, path=path)

        t0 = time.perf_counter()
        reloaded = load_json(path)
        elapsed = time.perf_counter() - t0
        assert elapsed < 1.0, f"load_json took {elapsed:.3f}s"
        assert len(reloaded.nodes) == len(doc.nodes)


class TestLargeFileScanSpeed:
    def test_500_function_file_parses_within_limit(self, tmp_path: Path):
        lines = ["# auto-generated large file\n"]
        for i in range(500):
            lines.append(
                f"def func_{i}(a, b, c):\n"
                f"    return a + b + c + {i}\n\n"
            )
        big = tmp_path / "big.py"
        big.write_text("".join(lines), encoding="utf-8")

        t0 = time.perf_counter()
        doc = run_scan(ScanOptions(root_path=tmp_path))
        elapsed = time.perf_counter() - t0

        assert elapsed < LARGE_FILE_PARSE_LIMIT_S, (
            f"500-function file took {elapsed:.3f}s "
            f"— expected under {LARGE_FILE_PARSE_LIMIT_S}s"
        )
        func_nodes = [n for n in doc.nodes if n.type.value == "FUNCTION"]
        assert len(func_nodes) == 500
