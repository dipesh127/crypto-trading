CREATE SCHEMA IF NOT EXISTS execution;

CREATE TABLE IF NOT EXISTS execution.orders (
  mode TEXT NOT NULL,
  symbol TEXT NOT NULL,
  exchange_order_id TEXT NOT NULL,
  client_order_id TEXT NOT NULL,
  side TEXT NOT NULL,
  order_type TEXT NOT NULL,
  status TEXT NOT NULL,
  orig_qty NUMERIC NOT NULL,
  executed_qty NUMERIC NOT NULL,
  avg_price NUMERIC NOT NULL,
  update_time TIMESTAMPTZ NOT NULL,
  latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
  request JSONB NOT NULL DEFAULT '{}'::jsonb,
  raw JSONB NOT NULL,
  PRIMARY KEY(mode, exchange_order_id, client_order_id)
);

CREATE TABLE IF NOT EXISTS execution.fills (
  mode TEXT NOT NULL,
  symbol TEXT NOT NULL,
  exchange_trade_id TEXT NOT NULL,
  exchange_order_id TEXT NOT NULL,
  client_order_id TEXT NOT NULL,
  side TEXT NOT NULL,
  price NUMERIC NOT NULL,
  qty NUMERIC NOT NULL,
  quote_qty NUMERIC NOT NULL,
  commission NUMERIC NOT NULL,
  commission_asset TEXT,
  trade_time TIMESTAMPTZ NOT NULL,
  raw JSONB NOT NULL,
  PRIMARY KEY(mode, exchange_trade_id, exchange_order_id, trade_time)
);
SELECT create_hypertable('execution.fills','trade_time',if_not_exists=>TRUE,chunk_time_interval=>INTERVAL '30 days');

CREATE TABLE IF NOT EXISTS execution.user_events (
  id BIGSERIAL PRIMARY KEY,
  mode TEXT NOT NULL,
  event_time TIMESTAMPTZ NOT NULL,
  event_type TEXT NOT NULL,
  payload JSONB NOT NULL
);
SELECT create_hypertable('execution.user_events','event_time',if_not_exists=>TRUE,chunk_time_interval=>INTERVAL '7 days');

CREATE TABLE IF NOT EXISTS execution.reconciliation_events (
  id BIGSERIAL PRIMARY KEY,
  mode TEXT NOT NULL,
  checked_at TIMESTAMPTZ NOT NULL,
  ok BOOLEAN NOT NULL,
  payload JSONB NOT NULL
);
SELECT create_hypertable('execution.reconciliation_events','checked_at',if_not_exists=>TRUE,chunk_time_interval=>INTERVAL '30 days');

CREATE INDEX IF NOT EXISTS idx_execution_orders_symbol_status ON execution.orders(symbol,status,update_time DESC);
CREATE INDEX IF NOT EXISTS idx_execution_reconcile_time ON execution.reconciliation_events(checked_at DESC);

CREATE TABLE IF NOT EXISTS execution.risk_events (
  id BIGSERIAL PRIMARY KEY,
  mode TEXT NOT NULL,
  event_time TIMESTAMPTZ NOT NULL DEFAULT now(),
  allowed BOOLEAN NOT NULL,
  action INTEGER,
  reasons TEXT[] NOT NULL DEFAULT '{}',
  flatten BOOLEAN NOT NULL DEFAULT FALSE,
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb
);
SELECT create_hypertable('execution.risk_events','event_time',if_not_exists=>TRUE,chunk_time_interval=>INTERVAL '30 days');
CREATE INDEX IF NOT EXISTS idx_execution_risk_time ON execution.risk_events(event_time DESC);
