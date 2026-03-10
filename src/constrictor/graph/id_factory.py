from __future__ import annotations

import hashlib


def create_id(prefix: str, *parts: str) -> str:
    """Create a deterministic, stable ID from a prefix and one or more parts.

    The parts are joined with '|', SHA256-hashed, and the first 16 hex chars
    are used. Format: `{prefix}:{hash}`, e.g. `func:a1b2c3d4e5f6a7b8`.
    """
    combined = "|".join(parts)
    digest = hashlib.sha256(combined.encode()).hexdigest()[:16]
    return f"{prefix}:{digest}"
