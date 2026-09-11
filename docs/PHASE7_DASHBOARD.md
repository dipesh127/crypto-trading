# Phase 7 — Dashboard

Production-oriented FastAPI + React dashboard. It follows the Phase 7 source specification: aggregated telemetry, WebSocket deltas, LTTB downsampling, keyset pagination, virtualization, Redis caching, Timescale continuous aggregates, and a dark responsive UI. The dashboard is read-only with respect to trading; Phase 6 remains the independent risk veto.

## Start backend

```bash
source .venv/bin/activate
python -m pip install -e ".[dev]"
psql "$POSTGRES_DSN" -f sql/003_dashboard.sql
python scripts/dashboard.py
```

Or after installation:

```bash
crypto-dashboard
```

API: `http://localhost:8000`.

## Start frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

For Docker Compose, the Vite proxy should target `http://dashboard:8000` and `ws://dashboard:8000` using `VITE_API_PROXY` / `VITE_WS_PROXY`.

## Data contract

Frontend endpoints:

- `/api/overview` — current account/risk/connection summary.
- `/api/metrics` — performance panel.
- `/api/timeseries/equity` — range-aware Timescale aggregate + LTTB.
- `/api/timeseries/price` — range-aware OHLC aggregate + LTTB.
- `/api/signals` — entry/exit signal markers.
- `/api/trades` — filterable, sortable keyset/cursor pagination; never OFFSET.
- `/api/metric-history` — sparkline data.
- `/api/diagnostics` — MLflow metrics/history when `MLFLOW_TRACKING_URI` is configured.
- `/api/alerts` — risk, reconciliation and exchange event feed.
- `/api/benchmarks` — precomputed backtest/benchmark comparison snapshots.
- `/ws/live` — changed-field deltas; the frontend patches local state instead of refetching datasets on every tick.

Hard response limits are 2,500 chart points and 250 trade rows. Range selection chooses 1m, 5m, 15m, 1h or 1d resolution. Multi-month ranges therefore use precomputed aggregates rather than raw 1-minute data.

## Database performance

`sql/003_dashboard.sql` adds Timescale continuous aggregates, covering indexes and dashboard snapshots. Run the verification script against the actual production-sized database:

```bash
python scripts/verify_dashboard_indexes.py
```

It executes `EXPLAIN (ANALYZE, BUFFERS)` for the exact trade-log and chart access patterns. Plans cannot be truthfully verified in an offline build environment; verify them after loading representative production-scale data.

## UI performance

- TradingView Lightweight Charts for candlesticks/signals.
- Recharts for bounded/downsampled equity and diagnostics.
- TanStack Virtual for trade rows.
- React.lazy code splitting for heavy dashboard sections.
- Animation disabled for large telemetry charts.
- WebSocket delta patching rather than full-data refresh.
- Dark mode by default, responsive overview/alerts, loading skeletons.

## Safety

The UI never places orders. `LIVE` is displayed distinctly from `PAPER / TESTNET`. Any future live execution must continue to pass through the Phase 6 risk manager and the existing Phase 5 execution/reconciliation path.
