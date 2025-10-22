# TODO: BTC–ETH Market-Neutral Stat-Arb (1h cadence) Project

awesome — here’s a crisp, end-to-end build plan your agent can execute to deliver an **hourly BTC–ETH market-neutral stat-arb (cointegration mean-reversion) scanner** that outputs trade tickets you can execute manually.

I’ve split it into: architecture, milestones, detailed agent tasks (with DoD/acceptance criteria), file layout, configs, and test plan. You can hand this straight to an agent and let it iterate.

---

## High-level architecture (hourly cadence)

1. **Data ingest (hourly)**
   - Pull 1h OHLCV for `BTC/USDT` and `ETH/USDT` (same exchange; recommend Binance).
   - Optional: pull perp **funding rates** for BTC/ETH (filter or annotation).

2. **Signal engine**
   - Rolling OLS on log prices to estimate hedge ratio β (e.g., 200 bars).
   - Compute spread `S_t = log(ETH) − β·log(BTC)`.
   - Z-score over L bars (e.g., 100).
   - Entry/exit: enter when `z` crosses ±2; exit when |z| < 0.5.
   - Risk rails: stop if |z| > 3.5; skip if liquidity/vol fails.

3. **Sizer + trade ticket**
   - Dollar-neutral with hedge ratio: long N ETH / short β·N BTC (or the opposite).
   - Vol targeting: scale N by 1 / (spread σ) to keep risk stable.
   - Apply fee/slippage assumptions in expected P&L.

4. **Outputs**
   - Human-readable **trade ticket** (symbol, side, notional, β, z, stops, est. fees).
   - CSV/SQLite logging of signals and P&L.
   - Notification (email/Slack/Telegram) when a **new** entry/exit signal triggers.

5. **Ops**
   - Run hourly via scheduler (cron/systemd/GitHub Actions).
   - Health checks, retries, idempotent runs.
   - Backtest + walk-forward evaluation.

---

## Milestones

- **M0: Project bootstrap**
- **M1: Data layer** (1h candles, local cache, unit tests)
- **M2: Signal engine** (β, spread, z, thresholds, state machine)
- **M3: Backtester** (vectorized sim with fees/slippage)
- **M4: Trade tickets + notifications**
- **M5: Scanner hardening** (filters, logging, dashboards)
- **M6: Deployment** (hourly job, secrets, monitoring)

---

## Agent task list (actionable, step-by-step)

### M0 — Bootstrap

1) **Create repo + env**
- **Tasks:**
  - Init git repo; add MIT license, README.
  - Create `pyproject.toml` (or `requirements.txt`).
  - Set up `pre-commit` (black/ruff).
- **Deps:** None
- **DoD:** Repo builds in a clean venv; `pytest -q` runs (even if no tests yet).

2) **Config & secrets**
- **Tasks:**
  - `.env.example` with:
    EXCHANGE=binance
    API_KEY=...
    API_SECRET=...
    NOTIFY_SLACK_WEBHOOK=...
    TIMEZONE=UTC
    BASE_QUOTE=USDT
  - Config YAML: strategy params (window_ols=200, window_z=100, z_in=2.0, z_out=0.5, z_stop=3.5, fee_bps=10, slippage_bps=5, min_adv_usd=5_000_000).
- **DoD:** `config.yaml` is loadable; secrets injected via `.env`.

---

### M1 — Data layer

3) **Exchange client (read-only)**
- **Tasks:**
  - Use `ccxt` to fetch **1h** klines for BTC/USDT & ETH/USDT.
  - Normalize columns: `ts, open, high, low, close, volume`.
  - Ensure same timestamps & no missing bars (forward-fill only if truly missing on both).
  - Optional: funding rates via `ccxt` or REST for perps.
- **DoD:** Function `load_ohlcv(pair, tf='1h', since, limit)` returns a clean `pd.DataFrame`. Retries + backoff included.

4) **Local cache**
- **Tasks:**
  - Append-only parquet/SQLite store of candles; dedup by `ts`.
  - Hourly refresh pulls only new bars.
- **DoD:** `data/cache/EXCHANGE_PAIR_TF.parquet` grows over time; reruns are idempotent.

5) **Liquidity metrics**
- **Tasks:**
  - Compute rolling ADV (USD) using `close*volume` and 30-bar SMA.
- **DoD:** `adv_usd` column exists; filterable.

---

### M2 — Signal engine

6) **Hedge ratio (rolling OLS)**
- **Tasks:**
  - Merge BTC/ETH frames by `ts`; add `logp`.
  - For each bar t ≥ `window_ols`, fit OLS: `logp_ETH ~ const + β * logp_BTC`.
  - Store β_t (use expanding or rolling 200 bars).
  - Efficiency: use rolling covariance formula or `statsmodels` in a loop with caching.
- **DoD:** `beta` series aligned to timestamps; handles NaNs at start; unit test with synthetic cointegrated series.

7) **Spread & z-score**
- **Tasks:**
  - `spread = logp_ETH − beta*logp_BTC`.
  - Rolling mean/std over `window_z` (e.g., 100).
  - `z = (spread − mean) / std`.
- **DoD:** `z` computed with NaNs pruned; reproducible over re-runs.

8) **State machine (entry/exit/stop)**
- **Tasks:**
  - Entry on **cross**:
    - Long-spread when `z_t > 2` crosses from ≤2 (short ETH/long BTC),
    - Short-spread when `z_t < −2` crosses from ≥−2 (long ETH/short BTC).
  - Exit when `|z| < 0.5`.
  - Hard stop when `|z| > 3.5`.
  - Only one position active at a time; carry state in persistent store.
- **DoD:** Deterministic transitions; unit tests for crossing logic and edge cases.

9) **Position sizing (vol targeting)**
- **Tasks:**
  - Compute spread σ (rolling std).
  - Target risk per trade (e.g., $R = 0.5% of account per 1σ move).
  - Solve notional N such that **P&L sensitivity to spread** aligns with R.
  - Convert to per-leg notionals with hedge ratio β.
  - Apply min/max notional caps; enforce ADV fraction (e.g., ≤5% ADV).
- **DoD:** `size_engine()` returns `(notional_eth, notional_btc)` and expected fee/slippage.

---

### M3 — Backtester

10) **Vectorized backtest**
- **Tasks:**
  - Simulate entries/exits with next-bar execution; include fees (both legs).
  - Track equity, drawdown, Sharpe, hit-rate, avg trade P&L, turnover.
  - Plot equity curve, z-score with trade markers.
- **DoD:** `backtest_report.html` saved; CLI `python -m app.backtest --config config.yaml` runs.

11) **Walk-forward**
- **Tasks:**
  - Split history (e.g., 70/30), refit β window and z window only on IS; apply on OOS.
  - Option: rolling walk-forward with refits every N bars.
- **DoD:** OOS metrics reported; parameters not leaking future info.

---

### M4 — Trade tickets & notifications

12) **Trade ticket generator**
- **Tasks:**
  - When a **new** entry triggers, emit a human-readable ticket:
    Timestamp (UTC)
    Signal: ENTER Long Spread (ETH long / BTC short)
    z = -2.36 (in < -2)
    β = 1.58 (window=200)
    Notional: +$10,000 ETH / -$15,800 BTC
    Stop: |z| > 3.5
    Exit on |z| < 0.5
    Est. fees: $X | Est. slippage: $Y
    Notes: funding symmetric; ADV ok
  - Same for exit/stop.
- **DoD:** Tickets saved to `signals/…` and printed to console.

13) **Notifications**
- **Tasks:**
  - Slack/Telegram webhook payloads for **entry/exit** only on **cross** events.
  - Debounce to avoid spam (e.g., 1 alert per direction per position).
- **DoD:** Test webhook hits a sandbox channel with sample payload.

---

### M5 — Hardening & dashboards

14) **Filters & guards**
- **Tasks:**
  - Skip signals if `adv_usd < threshold`, or if realized vol > cap, or if funding differential > cap (optional).
  - Add **persistence** layer (SQLite) for positions, last z, last β, last alert hash.
- **DoD:** Reruns are idempotent; no duplicate tickets; filters logged.

15) **Observability**
- **Tasks:**
  - Structured logging (JSON) with run id, bars fetched, latency, decisions.
  - Small HTML dashboard (Jinja) with latest z, β, live ticket, charts.
- **DoD:** `reports/index.html` updates each run.

---

### M6 — Deployment

16) **Scheduler**
- **Tasks:**
  - Cron (`@hourly`) or systemd timer; ensure start at minute +1 after exchange bar close.
  - Timezone consistency (use UTC internally).
- **DoD:** Two consecutive hourly runs produce exactly one decision cycle each.

17) **Container & runtime**
- **Tasks:**
  - Dockerfile (slim), .dockerignore, healthcheck that fetches 1 bar and exits 0.
  - Optional: GitHub Actions to run backtest on push, scanner on schedule.
- **DoD:** `docker run … scanner` executes and posts to webhook.

---

## File layout
```
stat-arb-btc-eth/
  README.md
  pyproject.toml            # or requirements.txt
  config.yaml               # strategy params
  .env.example
  src/
    data/
      exchange.py           # ccxt wrapper + retries
      cache.py              # parquet/sqlite cache
    features/
      beta.py               # rolling OLS hedge ratio
      spread.py             # spread & z-score
    strategy/
      state.py              # position state machine
      sizing.py             # vol targeting, fee/slippage
      filters.py            # adv/vol/funding checks
    backtest/
      simulator.py          # vectorized engine
      report.py             # metrics & plots
    runtime/
      scanner.py            # hourly job orchestrator
      tickets.py            # trade ticket formatter
      notify.py             # slack/telegram
    utils/
      config.py, logging.py, time.py
  tests/
    test_beta.py
    test_state.py
    test_backtest.py
  data/cache/
  signals/
  reports/
```


## Config knobs (starter defaults)
```
exchange: binance
symbols:
  base: ["BTC/USDT", "ETH/USDT"]
timeframe: "1h"
windows:
  ols_beta: 200
  zscore: 100
thresholds:
  z_in: 2.0
  z_out: 0.5
  z_stop: 3.5
risk:
  target_sigma_usd: 200.0     # P&L per 1.0 z move
  max_notional_usd_per_leg: 25000
  max_adv_frac: 0.05
costs:
  fee_bps: 10                 # 0.10% per leg
  slippage_bps: 5
filters:
  min_adv_usd: 5_000_000
  max_realized_vol_annual: 2.0
notifications:
  slack_webhook: "${NOTIFY_SLACK_WEBHOOK}"
```
---

## Prompts your agent can use (copy/paste)

**Implement rolling OLS hedge ratio**
> Write `beta.py` with a function `rolling_beta(logp_x, logp_y, window)` that returns a pd.Series β_t using a numerically stable rolling covariance approach (no for-loops). Include unit tests with synthetic cointegrated series to verify β ≈ true value.

**Build state machine**
> Implement `state.py` with a deterministic state machine that emits ENTER_LONG_SPREAD, ENTER_SHORT_SPREAD, EXIT, STOP events based on z and thresholds. Include tests for threshold crossings, idempotency, and stop precedence.

**Create vectorized backtester**
> Implement `simulator.py` to simulate next-bar execution, fees, slippage, and position sizing from `sizing.py`. Output equity curve, trade list, and summary stats. Verify with a fixed random walk that no trades occur, and with synthetic reversion that P&L > 0.

**Hourly scanner orchestration**
> Implement `scanner.py` that (1) refreshes caches, (2) computes β, spread, z, (3) runs state machine with persisted position, (4) generates trade ticket on new entries/exits, (5) posts Slack notification, and (6) writes a compact JSON log.

---

## Acceptance tests (quick)

- **Unit:**
  - β on synthetic: RMSE < 0.05 vs true β.
  - State machine crosses: exactly one entry alert when z crosses +2, not on every bar.
  - Sizer enforces β-neutral notionals within 1%.

- **Backtest sanity:**
  - On BTC–ETH 1h (≥1y), trades occur (~1–3/week), win-rate 55–65%, max DD < 10% at baseline sizing.
  - OOS walk-forward still positive after fees.

- **Ops:**
  - Rerunning the same hour does **not** duplicate tickets.
  - Slack alert fires once on entry and once on exit.
  - Cache grows only by 1 bar per run.

---

## Optional extensions (after MVP)

- **Funding differential filter:** avoid entries when |funding_btc − funding_eth| > X bps/8h.
- **Regime filter:** disable trades when realized spread vol > percentile(90%).
- **Multi-pair portfolio:** replicate pipeline for SOL–AVAX, MATIC–ARB, etc.
- **Dashboard:** lightweight `reports/index.html` with z-chart and live status.
- **Execution helper:** generate pre-filled orders (quantities) for your exchange UI.
