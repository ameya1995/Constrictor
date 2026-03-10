"""Unified diff parser for diff-aware impact analysis.

Parses a unified diff (output of ``git diff``) into a list of
``ChangedRegion`` objects that map file paths to the lines that changed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ChangedRegion:
    """A contiguous block of changed lines in a single file."""

    file_path: str
    line_start: int = 1
    line_end: int = 99_999


# Matches the +++ b/path line in a unified diff
_NEW_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$")
# Matches @@ -old_start[,old_count] +new_start[,new_count] @@
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def parse_diff(diff_text: str) -> list[ChangedRegion]:
    """Parse a unified diff string and return changed regions per file.

    Each hunk in the diff produces one ``ChangedRegion`` covering the
    added/modified lines on the *new* side of the diff.

    Files that are deleted (``--- a/...`` with ``+++ /dev/null``) are
    represented with line range (1, 99999) so that impact analysis still
    finds all their nodes.
    """
    regions: list[ChangedRegion] = []
    current_file: str | None = None

    for line in diff_text.splitlines():
        # New file header
        new_file_match = _NEW_FILE_RE.match(line)
        if new_file_match:
            current_file = new_file_match.group(1)
            continue

        # /dev/null target means deletion -- treat whole file as changed
        if line.startswith("+++ /dev/null"):
            if current_file is None:
                continue
            regions.append(ChangedRegion(file_path=current_file, line_start=1, line_end=99_999))
            current_file = None
            continue

        if current_file is None:
            continue

        # Hunk header
        hunk_match = _HUNK_RE.match(line)
        if hunk_match:
            start = int(hunk_match.group(1))
            count_str = hunk_match.group(2)
            count = int(count_str) if count_str is not None else 1
            end = start + max(count - 1, 0)
            regions.append(ChangedRegion(file_path=current_file, line_start=start, line_end=end))

    return regions


def merge_regions(regions: list[ChangedRegion]) -> list[ChangedRegion]:
    """Merge overlapping or adjacent regions for the same file."""
    by_file: dict[str, list[ChangedRegion]] = {}
    for r in regions:
        by_file.setdefault(r.file_path, []).append(r)

    merged: list[ChangedRegion] = []
    for fp, file_regions in sorted(by_file.items()):
        sorted_regions = sorted(file_regions, key=lambda r: r.line_start)
        current = sorted_regions[0]
        for nxt in sorted_regions[1:]:
            if nxt.line_start <= current.line_end + 1:
                current = ChangedRegion(
                    file_path=fp,
                    line_start=current.line_start,
                    line_end=max(current.line_end, nxt.line_end),
                )
            else:
                merged.append(current)
                current = nxt
        merged.append(current)

    return merged
