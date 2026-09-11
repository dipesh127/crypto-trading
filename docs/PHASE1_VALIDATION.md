# Phase 1 validation

1. `pytest -q`
2. `ruff check .`
3. `docker compose up -d postgres redis`
4. Confirm the SQL schema initializes without errors.
5. Run `python scripts/validate_testnet.py` with `APP_ENV=testnet`.
6. Confirm server-time offset is recorded/logged.
7. Confirm every configured symbol exists in `exchangeInfo`.
8. Confirm depth snapshots are returned.
9. Confirm WebSocket `aggTrade`, `depthUpdate`, `bookTicker`, and `markPriceUpdate`.
10. Verify order-book buffering, snapshot bridging, contiguous U/u ranges, and forced resync on gaps.
11. Verify raw data is never silently rewritten; quality problems become flags/events.
12. Keep Binance API withdrawal permission disabled and IP whitelist enabled.

### P0 runtime validation

- Start `python -m app.main` with TimescaleDB and Redis available; verify all configured symbols emit kline (1m/3m/5m/15m/1h/4h/1d), aggTrade, depth, bookTicker, markPrice, forceOrder, and ticker records.
- Verify `market.*` rows are persisted and Redis keys/streams (`market:book:*`, `market:features:*`, `market:*`) advance.
- Force a depth `pu`/`U` gap and verify a `system.data_quality_events` `GAP_DETECTED` record plus REST snapshot resynchronization.
- Run `python scripts/archive_market_data.py`; verify Parquet files are created before old raw rows are deleted.
- In paper/live execution, inject REST failures and verify each failed attempt calls `RiskManager.observe(rest_error=True)` and `execution.risk_events` records the resulting decision.
- Verify the live risk loop supplies 1m market realized volatility, rolling mean, and rolling standard deviation to the volatility circuit breaker.
- Verify paper and live execution both construct `PaperTradingEngine` with `RiskManager` and persist every risk decision.
- Verify liquidation-price tests across multiple leverage brackets and both long/short directions against Binance's tiered maintenance-rate + maintenance-amount formula.
