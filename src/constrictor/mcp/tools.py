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
                    "format": {
                        "type": "string",
                        "enum": ["full", "compact", "files"],
                        "description": (
                            "Output verbosity. "
                            "'full' returns complete node/edge objects (default). "
                            "'compact' returns (qualified_name, type, file:line) -- ~10x fewer tokens. "
                            "'files' returns only a deduplicated list of affected file paths."
                        ),
                        "default": "full",
                    },
                    "edge_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Only traverse edges of these types during BFS. "
                            "E.g. [\"CALLS\"] to restrict to call-graph edges only. "
                            "Valid values: IMPORTS, IMPORTS_FROM, CALLS, INHERITS, IMPLEMENTS, "
                            "CONTAINS, EXPOSES_ENDPOINT, CALLS_HTTP, FOREIGN_KEY, TYPE_ANNOTATED."
                        ),
                    },
                    "node_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Only include result nodes of these types.",
                    },
                    "file_pattern": {
                        "type": "string",
                        "description": (
                            "fnmatch glob to restrict result nodes by file path. "
                            "Prefix with '!' to exclude, e.g. '!tests/*'."
                        ),
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
                    "format": {
                        "type": "string",
                        "enum": ["full", "compact", "files"],
                        "description": (
                            "Output verbosity. "
                            "'full' returns complete node/edge objects (default). "
                            "'compact' returns summary tuples -- ~10x fewer tokens. "
                            "'files' returns only deduplicated file paths."
                        ),
                        "default": "full",
                    },
                    "edge_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Only traverse edges of these types when finding paths.",
                    },
                    "node_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Only yield paths whose intermediate nodes match these types.",
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
                    "format": {
                        "type": "string",
                        "enum": ["full", "compact", "files"],
                        "description": (
                            "Output verbosity. "
                            "'full' returns complete node objects (default). "
                            "'compact' returns (qualified_name, type, file:line). "
                            "'files' returns only deduplicated file paths."
                        ),
                        "default": "full",
                    },
                },
                "required": ["graph_path", "file_path"],
            },
        ),
        types.Tool(
            name="constrictor_search",
            description=(
                "Search the dependency graph for nodes by name or qualified name. "
                "Returns ranked candidates with their type and location. "
                "Use this before impact/paths to discover the exact node identifier. "
                "Supports partial names, qualified name fragments, and regex."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "graph_path": {
                        "type": "string",
                        "description": "Path to a previously written graph.json file.",
                    },
                    "query": {
                        "type": "string",
                        "description": (
                            "Search string. Partial name, qualified name fragment, or regex. "
                            "Case-insensitive. Results are ranked: exact > prefix > substring > regex."
                        ),
                    },
                    "node_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Restrict results to these node types, e.g. [\"FUNCTION\", \"CLASS\"]. "
                            "Valid values: MODULE, PACKAGE, CLASS, FUNCTION, METHOD, ENDPOINT, "
                            "VARIABLE, SQLALCHEMY_MODEL, TABLE, EXTERNAL_MODULE, EXTERNAL_SERVICE, "
                            "EXTERNAL_ENDPOINT, SERVICE, COMPONENT, JS_MODULE, JS_FUNCTION, JS_COMPONENT."
                        ),
                    },
                    "file_pattern": {
                        "type": "string",
                        "description": (
                            "fnmatch glob to restrict results by file path, e.g. 'app/routes/*'. "
                            "Only nodes whose file_path matches are returned."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return.",
                        "default": 10,
                    },
                },
                "required": ["graph_path", "query"],
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
        types.Tool(
            name="constrictor_file_context",
            description=(
                "Return a structured summary of all graph entities defined in a single file: "
                "classes (with bases), functions (with callees), endpoints, SQLAlchemy models, "
                "imports, and which other files import this one. "
                "Answers 'what is in this file?' in one call without reading source code."
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
                            "Path to the file to inspect. "
                            "Should match the file_path values stored in the graph."
                        ),
                    },
                },
                "required": ["graph_path", "file_path"],
            },
        ),
        types.Tool(
            name="constrictor_diff_impact",
            description=(
                "Determine the blast radius of a set of code changes expressed as a "
                "unified diff (from git diff) or explicit line ranges. "
                "Returns three tiers: directly_changed nodes, immediate_dependents (1 hop), "
                "and transitive_dependents (full blast radius). "
                "This is the ideal tool to run before committing a PR or refactor."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "graph_path": {
                        "type": "string",
                        "description": "Path to a previously written graph.json file.",
                    },
                    "diff": {
                        "type": "string",
                        "description": (
                            "A unified diff string (output of `git diff`). "
                            "Mutually exclusive with `changes`."
                        ),
                    },
                    "changes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "file_path": {"type": "string"},
                                "line_start": {"type": "integer"},
                                "line_end": {"type": "integer"},
                            },
                            "required": ["file_path"],
                        },
                        "description": (
                            "Explicit list of changed regions as {file_path, line_start, line_end}. "
                            "Mutually exclusive with `diff`."
                        ),
                    },
                    "format": {
                        "type": "string",
                        "enum": ["full", "compact", "files"],
                        "description": "Output verbosity (default: compact).",
                        "default": "compact",
                    },
                },
                "required": ["graph_path"],
            },
        ),
        types.Tool(
            name="constrictor_unused",
            description=(
                "Find potentially dead code: nodes with no incoming edges that are "
                "candidates for deletion. Groups results by file. "
                "Useful during cleanup, refactoring, or dependency audits."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "graph_path": {
                        "type": "string",
                        "description": "Path to a previously written graph.json file.",
                    },
                    "node_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Node types to check. Defaults to [\"FUNCTION\", \"METHOD\", \"CLASS\"]."
                        ),
                    },
                    "exclude_patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "fnmatch globs for file paths to skip, e.g. [\"tests/*\", \"**/__init__.py\"]."
                        ),
                    },
                    "entry_points": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Node name patterns to treat as 'used' even with no incoming edges. "
                            "Supports fnmatch globs, e.g. [\"main\", \"cli_*\", \"handle_*\"]."
                        ),
                    },
                },
                "required": ["graph_path"],
            },
        ),
        types.Tool(
            name="constrictor_batch_impact",
            description=(
                "Run impact analysis on multiple nodes simultaneously and return the "
                "merged, deduplicated blast radius. "
                "Use when renaming a class (class + all its methods), deleting a module "
                "(all exports), or planning a large refactor touching several symbols."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "graph_path": {
                        "type": "string",
                        "description": "Path to a previously written graph.json file.",
                    },
                    "nodes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "List of node identifiers (ID, qualified name, or display name). "
                            "Fuzzy matching is applied to each entry."
                        ),
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["downstream", "upstream"],
                        "default": "downstream",
                        "description": "Traversal direction (applied to all nodes).",
                    },
                    "max_depth": {
                        "type": "integer",
                        "default": 6,
                        "description": "Maximum BFS traversal depth.",
                    },
                    "format": {
                        "type": "string",
                        "enum": ["full", "compact", "files"],
                        "default": "compact",
                        "description": "Output verbosity.",
                    },
                },
                "required": ["graph_path", "nodes"],
            },
        ),
        types.Tool(
            name="constrictor_cycles",
            description=(
                "Detect circular dependencies in the graph. "
                "By default analyses only IMPORTS and IMPORTS_FROM edges. "
                "Returns all simple cycles sorted by length, with file paths. "
                "Use before adding a new import to verify no cycle would be created."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "graph_path": {
                        "type": "string",
                        "description": "Path to a previously written graph.json file.",
                    },
                    "edge_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Edge types to include in cycle detection. "
                            "Defaults to [\"IMPORTS\", \"IMPORTS_FROM\"]. "
                            "Other useful values: \"CALLS\", \"INHERITS\"."
                        ),
                    },
                },
                "required": ["graph_path"],
            },
        ),
    ]
