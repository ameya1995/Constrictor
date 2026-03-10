# Constrictor

Static dependency and blast-radius analyzer for Python codebases.  
Built for AI agents and developers who need to understand what breaks before they change something.

---

## What it does

Constrictor walks a Python project, parses every `.py` file into an AST, and builds a rich dependency graph. The graph captures:

- **Import relationships** — which modules depend on which
- **Call graphs** — which functions call which functions
- **Class hierarchies** — inheritance, ABC/Protocol implementations
- **Framework endpoints** — FastAPI, Flask, and Django routes
- **Database models** — SQLAlchemy and Django ORM with foreign-key relationships
- **HTTP calls** — outbound `requests`/`httpx` calls with static or dynamic URLs
- **Type annotations** — parameter and return type relationships
- **Service topology** — multi-service projects from `docker-compose.yml`, `Procfile`, and multiple `pyproject.toml` files

Every edge has a **certainty level** (`EXACT`, `INFERRED`, `AMBIGUOUS`, `UNRESOLVED`), so you always know how much to trust each relationship.

---

## Installation

```bash
pip install constrictor
```

**Requirements:** Python ≥ 3.10

**Optional dev dependencies:**

```bash
pip install "constrictor[dev]"   # adds pytest, ruff, mypy
```

---

## Quick Start

```bash
# 1. Scan your project and write a graph file
constrictor scan /path/to/your/project -o graph.json

# 2. See what breaks if you change a function
constrictor impact --node "app.utils::greet" --graph graph.json

# 3. Trace the dependency path between two nodes
constrictor paths --from "GET /users" --to "users" --graph graph.json
```

That's it. Constrictor scans Constrictor's own source in about 125 ms.

---

## CLI Reference

### `constrictor scan`

Scan a directory and build the dependency graph.

```
constrictor scan <path> [options]
```

| Flag | Default | Description |
|---|---|---|
| `-o`, `--output` | (stdout summary) | Write the graph JSON to this file |
| `-e`, `--exclude` | | Additional glob patterns to exclude (repeatable) |
| `--exclude-file` | | Path to a file containing additional exclude patterns (repeatable) |
| `-v`, `--verbose` | `False` | Show active ignore patterns, per-stage timings, and warnings |

**Without `-o`:** prints a one-paragraph human-readable summary.  
**With `-o graph.json`:** writes the full graph JSON; prints node/edge counts.

```bash
constrictor scan src/ -o graph.json --verbose
# Scanning: /path/to/src
# Active ignore patterns: 18
# Discovered 38 Python files. Parsed 38/38 successfully.
# Graph written to: graph.json
#   387 nodes, 988 edges
# Stage timings:
#   scan: 0.003s
#   parse: 0.021s
#   extract:imports: 0.008s
#   ...
```

---

### `constrictor impact`

Show the blast radius of a node — everything it affects (downstream) or everything that depends on it (upstream).

```
constrictor impact --node <id_or_name> [options]
```

| Flag | Default | Description |
|---|---|---|
| `-n`, `--node` | (required) | Node ID, qualified name, or display name |
| `-g`, `--graph` | `graph.json` | Path to the graph JSON file |
| `-d`, `--direction` | `downstream` | `downstream` (what this affects) or `upstream` (what depends on it) |
| `--depth` | `6` | Maximum traversal depth |
| `--no-ambiguous` | `False` | Exclude AMBIGUOUS and UNRESOLVED edges |

```bash
# What callers will be affected if I change greet()?
constrictor impact --node "app.utils::greet" --graph graph.json

# What does greet() depend on?
constrictor impact --node "app.utils::greet" --graph graph.json --direction upstream

# Impact of changing an endpoint
constrictor impact --node "GET /api/orders/{id}" --graph graph.json
```

**Exit codes:** `0` success, `1` node not found, `2` bad `--direction` value.

---

### `constrictor paths`

Find all dependency paths between two nodes.

```
constrictor paths --from <node> --to <node> [options]
```

| Flag | Default | Description |
|---|---|---|
| `-f`, `--from` | (required) | Source node ID or name |
| `-t`, `--to` | (required) | Target node ID or name |
| `-g`, `--graph` | `graph.json` | Path to the graph JSON file |
| `--depth` | `8` | Maximum path length (hops) |

```bash
constrictor paths --from "app.routes::create_order" --to "orders" --graph graph.json
# Path 1 (3 hops):
#   app.routes::create_order  (FUNCTION)
#     --[CALLS]-->
#   app.services::process_order  (FUNCTION)
#     --[CALLS]-->
#   orders  (TABLE)
```

Up to 20 paths are returned (capped to avoid combinatorial explosion).  
**Exit codes:** `0` success (including "no paths found"), `1` node not found.

---

### `constrictor audit`

List all ambiguous and unresolved edges for human review.

```
constrictor audit [--graph graph.json]
```

Use this after scanning to flag edges where Constrictor could not fully resolve a dependency. Each unresolved or ambiguous edge is a potential blind spot in your blast-radius analysis.

---

### `constrictor summary`

Print a human-readable summary of a graph file.

```
constrictor summary [--graph graph.json]
```

---

### `constrictor export`

Export the graph to different formats.

```bash
# JSON (equivalent to scan -o)
constrictor export json /path/to/project -o graph.json

# Neo4j bulk-import CSV files
constrictor export neo4j /path/to/project -o ./neo4j/
# Produces: nodes.csv, edges.csv
```

---

### `constrictor watch`

Watch for file changes and re-scan automatically.

```bash
constrictor watch /path/to/project -o graph.json
# Rescan triggered by: app/utils.py. Completed in 0.3s.
```

| Flag | Default | Description |
|---|---|---|
| `-o`, `--output` | `graph.json` | Output file path |
| `--debounce-ms` | `1500` | Debounce window for rapid saves |

---

### `constrictor serve`

Serve an interactive graph visualization in the browser.

```bash
constrictor serve --graph graph.json --port 8080
# Serving graph at http://127.0.0.1:8080
```

Features: force-directed D3.js visualization, node coloring by type, click-to-inspect, search box, filter by node type, service boundary clusters.

---

### `constrictor agent skill`

Generate a `SKILL.md` file for AI agent runtime discovery.

```bash
constrictor agent skill -o SKILL.md
```

This file instructs AI agents (Codex, Claude Code, Copilot, etc.) how to install and use Constrictor for pre-refactor blast-radius analysis.

---

## Output Schema (JSON)

The graph JSON file has this top-level structure:

```json
{
  "nodes": [...],
  "edges": [...],
  "scan_metadata": {...},
  "statistics": {...},
  "warnings": [...],
  "unresolved": [...]
}
```

### Node fields

| Field | Type | Description |
|---|---|---|
| `id` | `string` | Stable deterministic ID (`prefix:16hexchars`) |
| `type` | `NodeType` | One of the node types listed below |
| `name` | `string` | Short name (e.g. `greet`) |
| `qualified_name` | `string` | Dot-qualified name (e.g. `app.utils.greet`) |
| `display_name` | `string` | Human-readable name (e.g. `app.utils::greet`) |
| `file_path` | `string?` | Absolute path to the source file |
| `line_number` | `int?` | Line number of the definition |
| `certainty` | `int` | `0`=UNRESOLVED, `1`=AMBIGUOUS, `2`=INFERRED, `3`=EXACT |
| `metadata` | `dict[str, str]` | Extra data (e.g. `http_method`, `path` for endpoints) |

### Node types

| Type | Description |
|---|---|
| `MODULE` | A Python module (`.py` file) |
| `PACKAGE` | A Python package (directory with `__init__.py`) |
| `CLASS` | A class definition |
| `FUNCTION` | A module-level function |
| `METHOD` | A class method |
| `ENDPOINT` | An HTTP route endpoint |
| `SQLALCHEMY_MODEL` | A SQLAlchemy or Django ORM model class |
| `TABLE` | A database table (from `__tablename__` or Django `Meta`) |
| `EXTERNAL_MODULE` | A stdlib or third-party module |
| `EXTERNAL_ENDPOINT` | An outbound HTTP URL |
| `SERVICE` | A service defined in `docker-compose.yml` or `Procfile` |
| `COMPONENT` | A sub-package with its own `pyproject.toml` |

### Edge fields

| Field | Type | Description |
|---|---|---|
| `id` | `string` | Stable deterministic edge ID |
| `source_id` | `string` | ID of the source node |
| `target_id` | `string` | ID of the target node |
| `type` | `EdgeType` | One of the edge types listed below |
| `display_name` | `string` | Human-readable label |
| `file_path` | `string?` | File where this edge was observed |
| `line_number` | `int?` | Line number of the relationship |
| `certainty` | `int` | Same scale as node certainty |
| `metadata` | `dict[str, str]` | Extra data (e.g. `names` for `IMPORTS_FROM`) |

### Edge types

| Type | Description |
|---|---|
| `IMPORTS` | `import module` |
| `IMPORTS_FROM` | `from module import name` |
| `CALLS` | A function/method calls another |
| `RETURNS` | A function returns an instance of a class |
| `INHERITS` | Class inherits from another class |
| `IMPLEMENTS` | Class implements an ABC or Protocol |
| `CONTAINS` | Module contains a function/class; class contains a method |
| `EXPOSES_ENDPOINT` | Function is registered as an HTTP route handler |
| `INJECTS_DEPENDENCY` | Function parameter uses `Depends(...)` (FastAPI) |
| `CALLS_HTTP` | Function makes an outbound HTTP request |
| `DEFINES_MODEL` | ORM model class defines a database table |
| `HAS_COLUMN` | Table has a column (in metadata) |
| `FOREIGN_KEY` | Table has a foreign-key relationship to another table |
| `TYPE_ANNOTATED` | Function parameter or return is annotated with a class |
| `BELONGS_TO_SERVICE` | Module belongs to a service/component |
| `CROSSES_COMPONENT_BOUNDARY` | Edge crosses a service/component boundary |

### Certainty levels

Certainty tells you how confident Constrictor is about each relationship:

| Level | Value | When |
|---|---|---|
| `EXACT` | 3 | Statically resolved with full confidence |
| `INFERRED` | 2 | Likely correct but based on heuristics (e.g. third-party module detection) |
| `AMBIGUOUS` | 1 | Could not resolve to a specific target (e.g. dynamic attribute access) |
| `UNRESOLVED` | 0 | Could not resolve at all (parse error, broken import) |

When running `constrictor audit`, all `AMBIGUOUS` and `UNRESOLVED` edges are surfaced for review.

### statistics block

```json
{
  "total_files": 38,
  "parsed_files": 38,
  "failed_files": 0,
  "total_nodes": 387,
  "total_edges": 988,
  "node_type_counts": {"FUNCTION": 120, "MODULE": 38, ...},
  "edge_type_counts": {"CALLS": 310, "CONTAINS": 158, ...},
  "service_count": 0,
  "cross_component_edge_count": 0
}
```

---

## Ignore Patterns

Constrictor reads `.constrictor_ignore` from the project root. The format is one pattern per line, `#` for comments:

```
# Skip generated migrations
migrations/

# Skip test fixtures
tests/fixtures/
```

Default patterns are always applied:
`__pycache__`, `.git`, `.venv`, `venv`, `env`, `.env`, `node_modules`, `.tox`, `.nox`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `*.egg-info`, `dist`, `build`

Additional patterns can be passed with `--exclude` or `--exclude-file`.

---

## Agent Integration

Constrictor includes a `SKILL.md` generator for use with AI agent runtimes:

```bash
constrictor agent skill -o SKILL.md
```

### Recommended agent workflows

**Before refactoring a module:**
```bash
constrictor scan . -o graph.json
constrictor impact --node "app.services::process_order" --graph graph.json
# Review the blast radius before making changes
```

**Before reviewing a PR:**
```bash
# Scan both branches, diff the graphs
constrictor scan . -o before.json
git checkout feature-branch
constrictor scan . -o after.json
# Compare node/edge counts, look for removed nodes (deleted functions)
```

**Tracing data flow through a system:**
```bash
constrictor paths --from "POST /api/orders" --to "orders" --graph graph.json
# See every hop from the endpoint to the database table
```

**Cross-service impact analysis:**
```bash
constrictor impact --node "shared.models::Order" --graph graph.json
# Impact includes nodes in both the api and worker services
```

---

## Architecture

The scan pipeline runs in six stages:

```
┌─────────────────────────────────────────────────────────────────┐
│  1. scan_directory()        Walk the tree, apply ignore patterns│
│  2. parse_all()             AST-parse every .py file            │
│  3. GraphContributors       Ten extractors run in sequence:     │
│       ImportExtractor          import/from-import edges         │
│       ClassHierarchyExtractor  inheritance, CONTAINS            │
│       CallGraphExtractor       function call edges              │
│       FastAPIExtractor         @router.get/post/...             │
│       FlaskExtractor           @app.route(...)                  │
│       DjangoExtractor          urlpatterns, Model subclasses    │
│       SQLAlchemyExtractor      declarative_base, relationships  │
│       HTTPClientExtractor      requests/httpx calls             │
│       TypeAnnotationExtractor  parameter/return type edges      │
│       TopologyContributor      docker-compose, Procfile         │
│  4. post_process()          Tag cross-boundary edges            │
│  5. builder.build()         Sort, deduplicate, compute stats    │
│  6. export_json()           Serialize to stable JSON            │
└─────────────────────────────────────────────────────────────────┘
```

All IDs are **deterministic**: `SHA256(prefix + "|" + qualified_name)[:16]` in hex. The same code always produces the same graph.

---

## Contributing

### Adding a new extractor

1. Create `src/constrictor/analysis/my_extractor.py`
2. Implement the `GraphContributor` protocol:
   ```python
   class MyExtractor:
       name = "my_extractor"

       def contribute(
           self,
           parsed_modules: list[ParsedModule],
           builder: GraphBuilder,
           warnings: list[ScanWarning],
       ) -> None:
           # Walk AST nodes, call builder.add_node() and builder.add_edge()
           ...

       def post_process(self, builder: GraphBuilder) -> None:
           pass  # optional second pass
   ```
3. Register it in `src/constrictor/core/orchestrator.py` contributor list
4. Add tests in `tests/test_my_extractor.py`

### Running tests

```bash
pip install -e ".[dev]"
pytest tests/ -v --cov=constrictor --cov-report=term-missing
```

Target: > 80% line coverage on `core/`, `graph/`, and `analysis/` modules.

### Linting and type-checking

```bash
ruff check src/
mypy src/constrictor/
```

---

## Known Limitations

- **Dynamic attribute access:** `getattr(obj, method_name)()` calls cannot be statically resolved and produce `AMBIGUOUS` edges.
- **Dynamic imports:** `importlib.import_module(variable_name)` is detected as an `importlib` call but the target module is unknown.
- **Star imports:** `from module import *` is recorded as an `IMPORTS_FROM` edge with `names="*"` but individual names are not resolved.
- **Type comments:** PEP 484 type comments (`# type: ignore`) are not analyzed; only PEP 526 annotations are.
- **Multi-file class resolution:** If a class is defined in a file that isn't under the scan root, its node will have `EXTERNAL_MODULE` type.
- **`TYPE_CHECKING` blocks:** Imports inside `if TYPE_CHECKING:` are visible to the AST walker and will be added to the graph, but they are not verified at runtime.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
