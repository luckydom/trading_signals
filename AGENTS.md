# Repository Guidelines

## Project Structure & Module Organization
- `src/features`: Signal math (hedge ratio, spread, z-score).
- `src/strategy`: Trading logic (state machine, sizing).
- `src/runtime`: Orchestration (scanner, notifications, tickets).
- `src/backtest`: Vectorized backtester and metrics.
- `src/data`: Exchange client (CCXT) and local Parquet cache in `data/cache/`.
- `src/utils`: Config and logging helpers.
- `tests/`: Unit tests (configured, currently empty).
- Outputs: `signals/` trade tickets, `logs/` JSON logs.

## Build, Test, and Development Commands
- Create env: `python -m venv venv && source venv/bin/activate`
- Install deps: `pip install -r requirements.txt`
- Run scanner (single run): `python main.py scan --dry-run`
- Backtest: `python main.py backtest --config config.yaml`
- Update cache: `python main.py cache --update`
- Module entrypoints: `python -m src.runtime.scanner`, `python -m src.backtest.simulator`
- Lint/format (local): `ruff .` and `black .`

## Coding Style & Naming Conventions
- Python 3.9+; Black line length 100; Ruff for linting/imports.
- Use explicit names (no single-letter vars), snake_case for functions/variables, PascalCase for classes.
- Keep modules focused; avoid unrelated changes in the same PR.

## Testing Guidelines
- Framework: `pytest` with coverage to `src` (see `pyproject.toml`).
- Test files: `tests/test_*.py`; name tests after the module under test.
- Run tests: `pytest` or `pytest -q`.
- Add unit tests for feature calc, state transitions, and sizing math for new changes.

## Commit & Pull Request Guidelines
- Commit messages: concise, imperative (“Add backtest metric”, “Fix z-score NaN”).
- Prefer small, focused commits; reference issues where applicable (e.g., `Fixes #12`).
- PRs: clear description, scope of change, test plan/output, and any config impacts.

## Security & Configuration Tips
- Copy `.env.example` to `.env`. For notifications, remove leading `_` from env var names before use.
- For local dev without API keys, set `DEV_MODE=true` to bypass strict validation.
- Secrets stay in `.env` (git-ignored). Cached data lives under `data/cache/`.

## Architecture Overview
- Flow: cache update → signals (beta/spread/z) → filters (ADV) → state machine → sizing → ticket → notify.
- State persists at `data/state.json`; logs written to `logs/scanner.log` and `logs/runs/`.

