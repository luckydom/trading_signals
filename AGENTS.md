# Repository Guidelines

## Project Structure & Module Organization
- `src/features`: Signal math (hedge ratio, spread, z-score).
- `src/strategy`: Trading logic (state machine, sizing).
- `src/runtime`: Orchestration (batch scanner, notifications, tickets).
- `src/data`: Exchange client (CCXT) and local Parquet cache in `data/cache/`.
- `src/utils`: Config and logging helpers.
- `tests/`: Unit tests (configured, currently empty).
- Outputs: `signals/` trade tickets (write-only), `logs/` JSON logs.

## Build, Test, and Development Commands
- Create env: `python -m venv venv && source venv/bin/activate`
- Install deps: `pip install -r requirements.txt`
- Run batch scanner: `python -m src.runtime.batch_scanner` (adds/updates cache, computes signals, emits tickets, sends notifications)
- Dry run: `python -m src.runtime.batch_scanner --dry-run`
- Use cache only: `python -m src.runtime.batch_scanner --use-cache-only`
- Ignore ADV while in-position: `python -m src.runtime.batch_scanner --ignore-adv`
- Test Discord webhook only: `python -m src.runtime.batch_scanner --test-discord`
- Quick status (no notifications): `./check_status.py --show-all` (reads cache and prints latest z/beta)
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
 - Discord/Slack webhooks are read from `config.yaml` via env expansion in `src/utils/config.py` (e.g., `notifications.discord_webhook`).

## Architecture Overview
- Flow: cache update → signals (beta/spread/z) → filters (ADV) → state machine → sizing → ticket → per-ticket notify (with throttling).
- State persistence: per-pair files at `data/state_<pair>.json` (e.g., `data/state_btc_eth.json`). Created/updated on ENTRY/EXIT/STOP.
- Signals directory: `signals/` is output-only; no component reads from it.
- Logging: scanner logs at `logs/scanner.log`, per-run JSON in `logs/runs/`.

## Batch Scanner Behavior & Flags
- Reads enabled pairs from `config.yaml` → `pairs` list.
- ADV filter runs before state; use `--ignore-adv` if you need EXIT/STOP decisions while already in a position.
- `--level-trigger`: when NEUTRAL, allows entry on level (`|z| >= z_in`) without a crossing.
- Notifications: one message per ticket; throttle with `notifications.throttle_seconds` (default 0.75s).
- State seeding: if `previous_zscore` is missing, batch scanner seeds it from the prior bar to enable crossing detection.

## Removed/Legacy Entrypoints
- Single-pair scanner, backtester CLI, and paper-trading scripts were removed; batch scanner is the primary entrypoint.
