# Roadmap

This document tracks what's currently working, what's planned, and what's being explored. Specific items are tracked as GitHub Issues — feel free to open one to discuss or vote on priorities.

---

## What's in v0.1.0

The initial release covers the full core feature set:

- **Scan pipeline** — AST-based analysis of Python codebases with incremental re-scan support
- **Import graph** — `import` and `from ... import` relationships
- **Call graph** — function and method call edges
- **Class hierarchy** — inheritance, ABC/Protocol implementations
- **Framework extractors** — FastAPI, Flask, Django routes and ORM models
- **SQLAlchemy extractor** — declarative models, relationships, foreign keys
- **HTTP client extractor** — outbound `requests`/`httpx` calls
- **Type annotation extractor** — parameter and return type edges
- **JS/TS support** (optional) — imports, calls, and outbound HTTP via tree-sitter
- **Service topology** — multi-service detection via `docker-compose.yml` and `Procfile`
- **Certainty levels** — `EXACT`, `INFERRED`, `AMBIGUOUS`, `UNRESOLVED` on every edge
- **CLI** — `scan`, `impact`, `paths`, `audit`, `summary`, `export`, `watch`, `search`, `context`, `diff-impact`, `unused`, `cycles`, `serve`
- **MCP server** — 12 tools for AI agent integration (stdio and SSE transports)
- **Web UI** — interactive D3.js graph visualization
- **Agent skill generator** — `constrictor agent skill` produces a `SKILL.md` for agent runtimes

---

## Planned

These items are candidates for future releases. Open an issue to discuss or track progress.

- **PyPI publish** — first public release on PyPI
- **GitHub Actions release workflow** — automated publish on tag push
- **`constrictor init`** — interactive setup that writes a `.constrictor_ignore` and optionally generates a `SKILL.md`
- **Expanded JS/TS support** — React component trees, Next.js routes, module re-exports
- **Rust/Go extractor** — basic import and call graph for non-Python services in a monorepo
- **Watch + MCP** — `constrictor mcp serve --watch` to keep the graph live and notify clients on rescan
- **VS Code extension** — inline blast-radius hints in the editor
- **Persistent graph store** — optional SQLite or DuckDB backend instead of a flat JSON file
- **Smarter call resolution** — reduce `AMBIGUOUS` edges via type narrowing from annotations

---

## Not planned (out of scope)

- Runtime tracing or dynamic analysis — Constrictor is intentionally static-only
- IDE plugin for JetBrains — may revisit based on demand
- Supporting Python < 3.10

---

If you'd like to work on something from the Planned list, please open an issue first so we can discuss the design before you invest time in an implementation.
