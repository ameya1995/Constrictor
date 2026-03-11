# Constrictor

Static dependency and blast-radius analyzer for Python codebases. Answers "what breaks if I change X?" before you touch a line of code.

---

## Agent Integration

Constrictor is designed first for AI agents. Two integration paths are available.

### MCP server (Claude Code, Cursor, Copilot, Codex)

```bash
# 1. Install
pip install -e .

# 2. Scan the project once
constrictor scan . -o graph.json

# 3. Start the MCP server
constrictor mcp serve --graph graph.json
```

Add to your agent config (e.g. `.claude/mcp.json`, `~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "constrictor": {
      "command": "constrictor",
      "args": ["mcp", "serve", "--graph", "graph.json"]
    }
  }
}
```

**Available MCP tools:**

| Tool | Description |
|---|---|
| `constrictor_scan` | Scan a project and build the graph |
| `constrictor_impact` | Blast-radius analysis (downstream / upstream) |
| `constrictor_paths` | Enumerate dependency paths between two nodes |
| `constrictor_search` | Search nodes by name, type, or file pattern |
| `constrictor_file_context` | All entities defined in a single file |
| `constrictor_diff_impact` | Blast radius from a git diff or line ranges |
| `constrictor_batch_impact` | Merged impact analysis for multiple nodes |
| `constrictor_unused` | Find dead code candidates (no incoming edges) |
| `constrictor_cycles` | Detect circular import dependencies |
| `constrictor_dependents` | Find all dependents of a file |
| `constrictor_audit` | List ambiguous / unresolved edges |
| `constrictor_rescan_graph` | Rebuild `graph.json` in place after editing code |
| `constrictor_summary` | Human-readable graph summary + statistics |

**SSE transport** (for HTTP-based agent runtimes):
```bash
constrictor mcp serve --transport sse --port 9000
```

### SKILL.md (skill-file agents)

For agent runtimes that discover tools via skill files:

```bash
constrictor agent skill -o SKILL.md
```

### Common agent workflows

**Before refactoring:**
```bash
constrictor scan . -o graph.json
constrictor impact --node "app.services::process_order" --graph graph.json
```

**Before reviewing a PR:**
```bash
git diff HEAD~1 | constrictor diff-impact --graph graph.json
```

**Trace data flow to a database table:**
```bash
constrictor paths --from "POST /api/orders" --to "orders" --graph graph.json
```

**Find dead code:**
```bash
constrictor unused --graph graph.json --exclude "tests/*"
```

**Detect circular imports:**
```bash
constrictor cycles --graph graph.json
```

**After an agent edits files:**
```bash
# Ask the MCP server to rebuild graph.json in place
constrictor mcp serve --graph graph.json
```

Then call `constrictor_rescan_graph` from the agent before running impact or path analysis again.

---

## What it does

Constrictor parses every `.py` file into an AST and builds a rich dependency graph capturing:

- **Import relationships** — which modules depend on which
- **Call graphs** — which functions call which functions
- **Class hierarchies** — inheritance, ABC/Protocol implementations
- **Framework endpoints** — FastAPI, Flask, and Django routes
- **Database models** — SQLAlchemy and Django ORM with foreign-key relationships
- **HTTP calls** — outbound `requests`/`httpx` calls
- **Type annotations** — parameter and return type relationships
- **Service topology** — multi-service projects via `docker-compose.yml`, `Procfile`, multiple `pyproject.toml` files

Every edge has a **certainty level** (`EXACT`, `INFERRED`, `AMBIGUOUS`, `UNRESOLVED`).

---

## Installation

> Constrictor is not yet published to PyPI. Install from source.

```bash
git clone https://github.com/ameya1995/Constrictor.git
cd Constrictor
pip install -e .
# Optional: pip install -e ".[dev]"   # pytest, ruff, mypy
# Optional: pip install -e ".[js]"    # JS/TS support via tree-sitter
```

**Requirements:** Python ≥ 3.10

---

## CLI Reference

### `constrictor scan`
```bash
constrictor scan <path> -o graph.json [-v] [-i] [--include-js] [-e <glob>]
```
Scans `<path>` and writes the dependency graph. `-i` enables incremental re-scanning (uses `.constrictor_cache/`).

### `constrictor impact`
```bash
constrictor impact --node "app.utils::greet" --graph graph.json [--direction upstream|downstream] [--depth 6] [--format full|compact|files]
```
Blast-radius analysis for a single node.

### `constrictor diff-impact`
```bash
git diff HEAD~1 | constrictor diff-impact --graph graph.json [--format compact]
```
Maps every changed line in a unified diff to graph nodes; produces a tiered impact report.

### `constrictor paths`
```bash
constrictor paths --from "app.routes::create_order" --to "orders" --graph graph.json [--depth 8]
```
All dependency paths between two nodes (up to 20, capped to avoid combinatorial explosion).

### `constrictor search`
```bash
constrictor search "create_order" --graph graph.json [--type FUNCTION] [--limit 10]
```
Ranked by match quality: exact → prefix → substring → regex.

### `constrictor context`
```bash
constrictor context app/routes/users.py --graph graph.json
```
All entities (imports, functions, classes, endpoints, callers) defined in one file.

### `constrictor unused`
```bash
constrictor unused --graph graph.json [--exclude "tests/*"] [--entry-point "main"]
```

### `constrictor cycles`
```bash
constrictor cycles --graph graph.json [--edge-type CALLS]
```

### `constrictor watch`
```bash
constrictor watch /path/to/project -o graph.json [--debounce-ms 1500]
```
Re-scans incrementally on every file change.

### `constrictor audit` / `constrictor summary`
```bash
constrictor audit --graph graph.json      # list AMBIGUOUS/UNRESOLVED edges
constrictor summary --graph graph.json    # human-readable stats
```

### `constrictor export`
```bash
constrictor export neo4j /path/to/project -o ./neo4j/   # produces nodes.csv, edges.csv
```

### `constrictor serve`
```bash
constrictor serve --graph graph.json --port 8080
```
Interactive force-directed D3.js graph visualization in the browser.

### Web UI quick start

```bash
# 1. Build or refresh the graph
constrictor scan . -o graph.json

# 2. Start the browser UI
constrictor serve --graph graph.json --port 8080

# 3. Open the app
open http://127.0.0.1:8080
```

### How to use the UI

The web UI is organized as a three-column workspace:

- **Left panel**: view selection, focus controls, filters, and path inspector
- **Center panel**: interactive dependency graph or unresolved-audit list
- **Right panel**: metadata and blast-radius details for the currently selected node

**Recommended workflow:**

1. Start in **Workspace topology** for a full-project view.
2. Use **Node type** filters to remove noise before inspecting a subgraph.
3. Type in **Focus** to visually narrow the graph to matching nodes.
4. Click a node in the graph to open its metadata and impact analysis in the right panel.
5. Switch **Downstream / Upstream** to answer either "what does this affect?" or "what depends on this?".
6. Increase **Depth** when you want a broader blast radius.
7. Use **Path Inspector** when you need concrete paths between two nodes.

**Views:**

- **Workspace topology**: the full graph, useful for general exploration
- **Service/API dependencies**: emphasizes service, component, endpoint, and external-service nodes
- **Data/table impact**: emphasizes SQLAlchemy models, tables, modules, and packages
- **Unresolved audit**: shows ambiguous and unresolved edges in a readable review list

**Controls:**

- **Node type** filter: show or hide classes of nodes without rebuilding the graph on disk
- **Edge type** filter: restrict the rendered graph to one edge type such as `CALLS` or `IMPORTS`
- **Show ambiguous**: hide inferred/ambiguous edges when you want a cleaner exact-only visualization of the current graph
- **Path Inspector**: enter a `from` node and `to` node, then click **Find paths**

**Interpreting the graph:**

- Larger nodes usually represent higher-level entities like services and components
- Colored dashed hulls group nodes that belong to the same detected service/component boundary
- Selecting a node highlights directly connected neighbors and dims unrelated parts of the graph
- The top stat tiles are a quick orientation aid, not a replacement for detailed analysis

**Keeping the UI fresh after code changes:**

- If you are using the CLI directly, rerun `constrictor scan . -o graph.json`
- If you are using the MCP server, call `constrictor_rescan_graph` after a batch of edits
- If you want automatic refresh on file changes, use `constrictor watch . -o graph.json` in a separate terminal and reload the browser

**Current note:**

- The `Exact only` checkbox is present in the UI as a reserved control, but it is not wired to behavior yet. The working filter today is `Show ambiguous`.

---

## Output Schema (JSON)

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
| `type` | `NodeType` | `MODULE`, `PACKAGE`, `CLASS`, `FUNCTION`, `METHOD`, `ENDPOINT`, `SQLALCHEMY_MODEL`, `TABLE`, `EXTERNAL_MODULE`, `EXTERNAL_ENDPOINT`, `SERVICE`, `COMPONENT` |
| `name` | `string` | Short name (e.g. `greet`) |
| `qualified_name` | `string` | Dot-qualified (e.g. `app.utils.greet`) |
| `display_name` | `string` | Human-readable (e.g. `app.utils::greet`) |
| `file_path` | `string?` | Absolute path to source file |
| `line_number` | `int?` | Line number of definition |
| `certainty` | `int` | `3`=EXACT, `2`=INFERRED, `1`=AMBIGUOUS, `0`=UNRESOLVED |
| `metadata` | `dict` | Extra data (e.g. `http_method`, `path` for endpoints) |

### Edge fields

| Field | Type | Description |
|---|---|---|
| `id` | `string` | Stable deterministic edge ID |
| `source_id` / `target_id` | `string` | Node IDs |
| `type` | `EdgeType` | `IMPORTS`, `IMPORTS_FROM`, `CALLS`, `RETURNS`, `INHERITS`, `IMPLEMENTS`, `CONTAINS`, `EXPOSES_ENDPOINT`, `INJECTS_DEPENDENCY`, `CALLS_HTTP`, `DEFINES_MODEL`, `HAS_COLUMN`, `FOREIGN_KEY`, `TYPE_ANNOTATED`, `BELONGS_TO_SERVICE`, `CROSSES_COMPONENT_BOUNDARY` |
| `certainty` | `int` | Same scale as node certainty |
| `file_path` / `line_number` | | Where the relationship was observed |
| `metadata` | `dict` | Extra data (e.g. `names` for `IMPORTS_FROM`) |

All IDs are deterministic: `SHA256(prefix + "|" + qualified_name)[:16]` in hex.

---

## Ignore Patterns

Add a `.constrictor_ignore` file at the project root (one pattern per line, `#` for comments). Default exclusions: `__pycache__`, `.git`, `.venv`, `venv`, `node_modules`, `dist`, `build`, and common cache directories. Extra patterns via `--exclude` or `--exclude-file`.

---

## Known Limitations

- `getattr(obj, method_name)()` — dynamic calls produce `AMBIGUOUS` edges
- `importlib.import_module(variable)` — target module is unknown
- `from module import *` — individual names are not resolved
- PEP 484 type comments are not analyzed (only PEP 526 annotations)
- Classes defined outside the scan root appear as `EXTERNAL_MODULE` nodes
- Imports inside `if TYPE_CHECKING:` are included in the graph but not runtime-verified

---

## Contributing

```bash
pip install -e ".[dev]"
pytest tests/ -v --cov=constrictor --cov-report=term-missing
ruff check src/
mypy src/constrictor/
```

To add a new extractor: implement the `GraphContributor` protocol (`contribute` + optional `post_process`), register it in `src/constrictor/core/orchestrator.py`, and add tests.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
