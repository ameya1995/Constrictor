"""MCP tool definitions for Constrictor.

Input/output schemas are derived from the existing Pydantic models so there
is no duplication -- the shapes here just mirror what GraphQueryEngine already
returns, expressed as JSON Schema for the MCP protocol layer.
"""

from __future__ import annotations

from mcp import types


def get_tool_definitions() -> list[types.Tool]:
    """Return the list of MCP tools exposed by Constrictor."""
    return [
        types.Tool(
            name="constrictor_scan",
            description=(
                "Scan a Python project directory and build a dependency graph. "
                "Returns scan statistics and metadata. Optionally writes the full "
                "graph JSON to disk so other tools can load it without re-scanning."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Absolute path to the Python project root to scan.",
                    },
                    "output_path": {
                        "type": "string",
                        "description": (
                            "Optional path to write graph.json. "
                            "If omitted the graph is kept in memory only."
                        ),
                    },
                    "exclude_patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Additional glob patterns to exclude from the scan.",
                    },
                    "incremental": {
                        "type": "boolean",
                        "description": (
                            "If true, only re-analyze files that changed since the last "
                            "scan. Falls back to a full scan when the cache is absent."
                        ),
                        "default": False,
                    },
                },
                "required": ["project_path"],
            },
        ),
        types.Tool(
            name="constrictor_impact",
            description=(
                "Find the blast radius of a node -- all nodes reachable by following "
                "edges outward (downstream) or inward (upstream). Answers 'what breaks "
                "if I change X?' or 'what does X depend on?'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "graph_path": {
                        "type": "string",
                        "description": "Path to a previously written graph.json file.",
                    },
                    "node": {
                        "type": "string",
                        "description": (
                            "Node to analyse. Accepts a node ID, qualified name, or "
                            "display name (fuzzy matching is applied)."
                        ),
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["downstream", "upstream"],
                        "description": (
                            "downstream: what does this node affect? "
                            "upstream: what depends on this node?"
                        ),
                        "default": "downstream",
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum BFS traversal depth.",
                        "default": 6,
                    },
                    "include_ambiguous": {
                        "type": "boolean",
                        "description": "Include AMBIGUOUS and UNRESOLVED certainty edges.",
                        "default": True,
                    },
                },
                "required": ["graph_path", "node"],
            },
        ),
        types.Tool(
            name="constrictor_paths",
            description=(
                "Enumerate all dependency paths between two nodes. Useful for tracing "
                "data flow from an API endpoint to a database table, or between any two "
                "points in the codebase."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "graph_path": {
                        "type": "string",
                        "description": "Path to a previously written graph.json file.",
                    },
                    "from_node": {
                        "type": "string",
                        "description": "Source node (ID, qualified name, or display name).",
                    },
                    "to_node": {
                        "type": "string",
                        "description": "Target node (ID, qualified name, or display name).",
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum path depth (hops).",
                        "default": 8,
                    },
                },
                "required": ["graph_path", "from_node", "to_node"],
            },
        ),
        types.Tool(
            name="constrictor_audit",
            description=(
                "List all AMBIGUOUS and UNRESOLVED edges in the graph. "
                "These are edges where Constrictor could not statically resolve the "
                "target -- they may indicate dynamic imports, complex call patterns, "
                "or cases that need human review."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "graph_path": {
                        "type": "string",
                        "description": "Path to a previously written graph.json file.",
                    },
                },
                "required": ["graph_path"],
            },
        ),
        types.Tool(
            name="constrictor_dependents",
            description=(
                "Find all nodes that depend on (are upstream consumers of) any node "
                "defined in a given file. Answers: 'what breaks if I change this file?'"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "graph_path": {
                        "type": "string",
                        "description": "Path to a previously written graph.json file.",
                    },
                    "file_path": {
                        "type": "string",
                        "description": (
                            "Absolute or relative path to the Python file. "
                            "Must match the file_path values stored in the graph."
                        ),
                    },
                },
                "required": ["graph_path", "file_path"],
            },
        ),
        types.Tool(
            name="constrictor_summary",
            description=(
                "Return a human-readable summary of the dependency graph plus the raw "
                "statistics block. Useful as a quick orientation for an AI agent before "
                "running more targeted queries."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "graph_path": {
                        "type": "string",
                        "description": "Path to a previously written graph.json file.",
                    },
                },
                "required": ["graph_path"],
            },
        ),
    ]
