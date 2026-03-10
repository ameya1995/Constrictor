# Contributing to Constrictor

Thanks for your interest in contributing! This document covers how to set up your environment, run tests, and submit changes.

---

## Getting started

```bash
git clone https://github.com/ameya1995/Constrictor.git
cd Constrictor
pip install -e ".[dev]"
```

For JS/TS analysis support:

```bash
pip install -e ".[js]"
```

---

## Running tests

```bash
pytest tests/ -v --cov=constrictor --cov-report=term-missing
```

Target: > 80% line coverage on `core/`, `graph/`, and `analysis/` modules.

---

## Linting and type-checking

```bash
ruff check src/
mypy src/constrictor/
```

Both must pass cleanly before submitting a PR.

---

## Adding a new extractor

Extractors live in `src/constrictor/analysis/`. To add support for a new framework or pattern:

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
3. Register it in `src/constrictor/core/orchestrator.py`
4. Add tests in `tests/test_my_extractor.py`

---

## Submitting a pull request

1. Fork the repo and create a branch from `main`.
2. Make your changes with tests.
3. Ensure `pytest`, `ruff check`, and `mypy` all pass.
4. Open a PR with a clear description of what changed and why.

For larger changes, open an issue first to discuss the approach before investing time in an implementation.

---

## Reporting bugs

Use the [bug report template](https://github.com/ameya1995/Constrictor/issues/new?template=bug_report.md). Include:

- Python version and OS
- The command you ran
- The full error output
- A minimal reproducer if possible

---

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating you agree to abide by its terms.
