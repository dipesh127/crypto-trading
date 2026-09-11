# Phase 5 — Real-Time Binance Futures Testnet Paper Trading

## Scope

Phase 5 executes the **same Stable-Baselines3 inference facade used by Phase 4** against Binance USDⓈ-M Futures Testnet. It does not call the Phase 3 simulator for fills.

`checkpoint -> TrainedPolicy.predict() -> BinanceFeatureStore -> PaperTradingEngine -> BinancePaperExecutionAdapter -> Binance Testnet`

The adapter is deliberately testnet-only unless an explicit future live adapter is introduced.

## Binance integration

- Signed REST order placement: `POST /fapi/v1/order`.
- Position reconciliation: `GET /fapi/v3/positionRisk`.
- Open-order reconciliation: `GET /fapi/v1/openOrders`.
- Authenticated user-data listen key lifecycle: create/keepalive/close.
- User stream consumption: `ORDER_TRADE_UPDATE`, `ACCOUNT_UPDATE`, `MARGIN_CALL`, and `listenKeyExpired`.
- Automatic websocket reconnect with exponential backoff.
- Listen-key keepalive every 30 minutes.
- Exchange event latency is measured from local order submission to REST response and persisted.

Binance recommends user-data WebSocket events for orders/positions over delayed REST responses, so the local state is event-driven and REST is used for bootstrap/reconciliation. The user stream is also periodically renewed and reconnects after expiry/disconnect.

## Database

Apply both migrations:

```bash
psql "$POSTGRES_DSN" -f sql/001_phase1.sql
psql "$POSTGRES_DSN" -f sql/002_execution.sql
```

or:

```bash
python scripts/init_execution_db.py
```

`execution.orders`, `execution.fills`, `execution.user_events`, and `execution.reconciliation_events` use a `mode` column. `PAPER_TESTNET` and the future `LIVE` adapter therefore share the same persistence format.

## Checkpoint requirements

The metadata file must contain at least:

```json
{
  "feature_columns": ["..."],
  "feature_set_version": "...",
  "feature_code_sha256": "...",
  "schema_hash": "...",
  "observation_window": 60
}
```

The real-time feature store computes only closed klines and does not refit scalers. If the checkpoint used a scaler, load the persisted scaler state from its training artifact before calling the policy.

## Run

```bash
python scripts/paper_trade.py \
  --model artifacts/models/champion.zip \
  --metadata artifacts/models/champion.json \
  --symbol BTCUSDT \
  --quantity 0.001
```

This requires `APP_ENV=testnet` and Binance Testnet API credentials in `.env`.

## Reconciliation

The paper process runs reconciliation every 30 seconds by default. A one-shot check is also available:

```bash
python scripts/reconcile.py --symbol BTCUSDT
```

A mismatch is persisted and sent to the configured alert callback. Position quantity and entry price, plus the open-order client-ID set, are checked.

## Safety boundary

Do not put production Binance credentials into this Phase 5 testnet configuration. Production execution is intentionally not enabled by the supplied command.
