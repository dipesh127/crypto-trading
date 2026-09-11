# Phase 8 — Go-Live

Phase 8 enables production trading only after a fail-closed promotion gate. It does **not** auto-promote models or capital.

## Required gates

1. Minimum 8 profitable paper weeks.
2. Minimum 200 paper trades.
3. Maximum paper drawdown <= 15%.
4. Results cover at least three distinct market regimes (bull, bear, range/chop).
5. All Phase 6 risk controls tested and active.
6. Current champion checkpoint and feature manifest are identified.
7. Human sign-off is explicit, named, recent, and recorded.
8. Production API key is separate from Testnet credentials.
9. API key is IP-restricted and withdrawals are disabled. The application requires explicit security attestations and fails closed if they are absent; it cannot independently change Binance account-level API permissions.
10. Production REST endpoint is `https://fapi.binance.com`; the live user stream is the production USDⓈ-M stream. Binance recommends prioritizing user-data WebSocket state for orders/positions during volatile conditions. See current Binance documentation.

## Evidence

Create a JSON evidence file without secrets:

```json
{
  "profitable_weeks": 8,
  "trade_count": 250,
  "max_drawdown": 0.10,
  "market_regimes": ["bull", "bear", "range"],
  "risk_controls_tested": true,
  "human_signoff": true,
  "signoff_name": "Human Reviewer",
  "signoff_at": "2026-09-09T08:00:00+05:45",
  "model_checkpoint": "artifacts/models/champion.zip",
  "feature_set_version": "phase2-v1",
  "paper_start": "2026-07-01T00:00:00Z",
  "paper_end": "2026-09-01T00:00:00Z",
  "notes": "Manual review completed."
}
```

## Environment

Production execution requires all of these to be explicitly true:

```env
APP_ENV=live
LIVE_TRADING_ENABLED=true
LIVE_HUMAN_SIGNOFF=true
BINANCE_REST_BASE_URL=https://fapi.binance.com
BINANCE_WS_BASE_URL=wss://fstream.binance.com
BINANCE_API_KEY=<production-trade-key>
BINANCE_API_SECRET=<production-secret>
BINANCE_IP_WHITELISTED=true
BINANCE_WITHDRAWALS_DISABLED=true
```

Never reuse Testnet credentials for production.

## Preflight — no orders are placed

```bash
python scripts/go_live_preflight.py --evidence artifacts/go_live/evidence.json
```

The command exits non-zero if any gate fails.

## Live execution

```bash
python scripts/live_trade.py \
  --model artifacts/models/champion.zip \
  --metadata artifacts/models/champion.json \
  --evidence artifacts/go_live/evidence.json \
  --symbol BTCUSDT \
  --quantity 0.001
```

The same `PaperTradingEngine`, `TrainedPolicy`, `BinanceFeatureStore`, risk layer, reconciliation service, client-order-id idempotency and execution state path are used. The only execution-mode difference is the endpoint/account and database mode (`LIVE`).

## Capital ramp

Start at the Phase 6 minimum ramp fraction (10% of the approved live allocation). Each subsequent increase requires the configured dwell period, positive PnL, acceptable drawdown, and explicit human approval. There is no automated path to 100% capital.

## Monitoring and retraining

Live mode continues to use:

- Dashboard telemetry and alerts
- Reconciliation
- Phase 6 daily-loss and connectivity kill switches
- Volatility and leverage limits
- Feature PSI/KL drift
- Rolling Sharpe decay
- Champion/challenger evaluation
- Human-reviewed model promotion and rollback

A challenger is never promoted merely because its backtest is better; it must pass paper/shadow evaluation and receive human approval.
