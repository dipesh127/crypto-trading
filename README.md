# Crypto RL Trader — Phase 8.1 Full Specification Build

Phase 2 adds a unit-tested feature-engineering layer on top of the Phase 1 market-data foundation.

## Install
Use the same Python environment that passed Phase 1:

```bash
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Test
```bash
python -m pytest -q
ruff check app tests
```

## Feature groups
- returns, rolling volatility, z-score/min-max normalization
- SMA, EMA, MACD
- ADX, +DI, -DI, DX
- Ichimoku
- RSI (Wilder), Stochastic, CCI, ROC, Williams %R
- Bollinger Bands, bandwidth, ATR (Wilder), Keltner Channels
- OBV, VWAP, CVD
- OBI, weighted microprice, absolute/relative spread
- Cont-Kukanov-Stoikov OFI
- rolling Kyle lambda
- funding level/ROC, futures-spot basis
- OI momentum + four-quadrant OI/price regime
- rolling liquidation clusters by side
- Hurst R/S, rolling skewness/kurtosis
- KMeans/GMM market regime classifier
- 1m/5m/15m/1h multi-timeframe feature concatenation
- checkpoint feature-code SHA256 + schema hash + scaler state

## Leakage policy
All feature transforms are timestamp-causal. The default Ichimoku output is feature-safe: Senkou values are retained at their calculation timestamp rather than shifted into the future, and Chikou is not shifted backward. `shifted=True` exists only for charting/analysis and must not be fed to the model. Scalers and regime models are fit on training data only.


## Phase 4
See `docs/PHASE4_RL.md`. RL dependencies are declared in `pyproject.toml`.

## Phase 5

Real-time Binance Futures Testnet paper execution is implemented in `app/paper.py`, with shared policy inference in `app/rl/live_policy.py` and state reconciliation in `app/reconciliation.py`. Apply `sql/002_execution.sql` before using database logging.

## Phase 7 Dashboard

Phase 7 adds a FastAPI telemetry backend and a Vite/React dashboard. It serves pre-aggregated chart data, LTTB-downsampled series, keyset-paginated trade logs, Redis-cached metrics, and WebSocket deltas. See `docs/PHASE7_DASHBOARD.md`.

## Phase 8 — Go-Live

Production execution is fail-closed. See `docs/PHASE8_GOLIVE.md`.

- `app/golive.py`: evidence gate and security attestation
- `app/live.py`: production Binance adapter reusing the Phase 5 execution path
- `scripts/go_live_preflight.py`: no-order promotion preflight
- `scripts/live_trade.py`: production runner using the same policy/feature/execution engine path
- `sql/004_golive.sql`: human review, capital-ramp and challenger governance audit tables

The system never auto-promotes a model or capital. Production credentials must be separate from Testnet, IP-restricted, and configured with withdrawals disabled. These account-level settings are manually attested because the application cannot safely change or independently verify all Binance API-management permissions.

## Phase 8.1 Hardened Go-Live

Phase 8.1 makes the remaining production governance controls runtime-enforced:

1. The first live activation must use ramp stage 0 (10%). Later stages can only be activated through `scripts/advance_ramp.py`, after the minimum dwell/performance checks and named human sign-off.
2. Every opening order passes the active capital-ramp limit in the independent risk layer.
3. Live inference continuously feeds equity returns, current features, WebSocket health and REST errors into `RiskManager.observe()`.
4. `LiveGovernanceSupervisor` runs for the lifetime of the live process. Risk pauses are fail-closed; configured drift/performance pauses can trigger a challenger retraining command.
5. Challenger retraining can only create a challenger/shadow artifact. It cannot promote a model to production.
6. Promotion and rollback require explicit human reviewer/sign-off.

Apply `sql/005_phase81_governance.sql` after the previous migrations.

## Phase 1 P0 market-data operations

Run the ingestion service with `python -m app.main`. It bootstraps exchange metadata, leverage brackets,
recent klines/funding/OI/top-trader history, then starts Binance combined streams for all configured
klines, aggTrade, depth, bookTicker, mark price, and forceOrder. Raw market data is written to TimescaleDB,
current state is mirrored to Redis and Redis Streams, and order-book gaps/outliers are recorded as quality events.

Archive/delete raw tick data after the configured retention window with:
`python scripts/archive_market_data.py --days 60 --out data/archive`.
OHLCV klines are retained indefinitely.


## Production data path
Run `python scripts/market_data_service.py` (or the Compose `market-ingestion` service) before paper/live inference. Market inference consumes Redis market streams/hot state and PostgreSQL only for warm-start history; it does not poll market REST endpoints per inference cycle.


## Account-state lifecycle hardening

A1 defines the canonical account observation contract shared by the RL environment and paper/live inference. A2 adds persistent position lifecycle recovery: opening timestamps are preserved across restarts, reconstructed from the durable fill journal when available, and recovered from Binance user-trade history when local fills are incomplete. Partial adds preserve the original timestamp; closes clear it; reversals begin a new lifecycle.
