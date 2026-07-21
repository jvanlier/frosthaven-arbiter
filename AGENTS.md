# Agent Instructions

## Package management

- Lock packages with `just lock` instead of `uv lock`.
- Install/sync packages with `just sync` instead of `uv sync`.

## Testing

- Run the default test suite (excludes e2e, includes coverage) with `just test` or `uv run pytest`.
- Coverage has an enforced floor of 80% (`pyproject.toml` `[tool.coverage.report]`); a coverage shortfall fails the run.
- Browser-driven e2e tests are opt-in and excluded by default: `just test-e2e` (requires `uv run playwright install chromium` once).
- To run a single test file or test, pass it through to pytest, e.g. `uv run pytest tests/test_web.py -k index_page --no-cov`.

## Validation before finishing a change

Run all of the following; all must pass before considering work done:

1. `just test` (or `uv run pytest`)
2. `just lint` (runs both of the below), or individually:
   - `just lint-python` -> `uv run ruff format --check .`, `uv run ruff check .`, `uv run pyright`
   - `just lint-web` -> `uv run djlint src/frosthaven_arbiter/web/templates`
3. Pre-commit hooks run automatically on commit (ruff format/check, pyright, djlint on templates, end-of-file-fixer, trailing-whitespace, merge-conflict/toml/yaml checks). If a hook rewrites files, inspect and include those changes deliberately.
