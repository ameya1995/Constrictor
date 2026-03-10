from __future__ import annotations

import json
from pathlib import Path

from constrictor.graph.models import GraphDocument


def export_json(
    document: GraphDocument,
    path: Path | None = None,
    pretty: bool = True,
) -> str:
    """Serialize a GraphDocument to JSON.

    Returns the JSON string. If `path` is given, also writes it to that file.
    """
    data = document.model_dump(mode="json")
    indent = 2 if pretty else None
    json_str = json.dumps(data, indent=indent, sort_keys=True)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json_str, encoding="utf-8")
    return json_str


def load_json(path: Path) -> GraphDocument:
    """Deserialize a GraphDocument from a JSON file."""
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    return GraphDocument.model_validate(data)
