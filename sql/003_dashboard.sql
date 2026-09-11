CREATE SCHEMA IF NOT EXISTS dashboard;

CREATE TABLE IF NOT EXISTS dashboard.equity_snapshots (
  mode TEXT NOT NULL,
  ts TIMESTAMPTZ NOT NULL,
  equity NUMERIC NOT NULL,
  drawdown NUMERIC,
  unrealized_pnl NUMERIC,
  today_pnl NUMERIC,
  leverage NUMERIC,
  margin_ratio NUMERIC,
  PRIMARY KEY(mode, ts)
);
SELECT create_hypertable('dashboard.equity_snapshots','ts',if_not_exists=>TRUE,chunk_time_interval=>INTERVAL '30 days');

CREATE TABLE IF NOT EXISTS dashboard.signal_events (
  mode TEXT NOT NULL,
  ts TIMESTAMPTZ NOT NULL,
  symbol TEXT NOT NULL,
  signal TEXT NOT NULL,
  price NUMERIC NOT NULL,
  indicators JSONB NOT NULL DEFAULT '{}',
  model_version TEXT,
  PRIMARY KEY(mode,symbol,ts)
);
SELECT create_hypertable('dashboard.signal_events','ts',if_not_exists=>TRUE,chunk_time_interval=>INTERVAL '7 days');

CREATE TABLE IF NOT EXISTS dashboard.benchmark_snapshots (
  mode TEXT NOT NULL,
  benchmark TEXT NOT NULL,
  period_start TIMESTAMPTZ NOT NULL,
  period_end TIMESTAMPTZ NOT NULL,
  total_return NUMERIC,
  sharpe NUMERIC,
  max_drawdown NUMERIC,
  trade_count INTEGER,
  PRIMARY KEY(mode,benchmark,period_start,period_end)
);

CREATE TABLE IF NOT EXISTS dashboard.model_diagnostics (
  run_id TEXT NOT NULL,
  step BIGINT NOT NULL,
  ts TIMESTAMPTZ NOT NULL,
  reward NUMERIC,
  policy_loss NUMERIC,
  value_loss NUMERIC,
  entropy NUMERIC,
  PRIMARY KEY(run_id,step)
);
SELECT create_hypertable('dashboard.model_diagnostics','ts',if_not_exists=>TRUE,chunk_time_interval=>INTERVAL '30 days');

CREATE MATERIALIZED VIEW IF NOT EXISTS dashboard.equity_5m
WITH (timescaledb.continuous) AS
SELECT mode, time_bucket('5 minutes', ts) bucket, last(equity,ts) equity,
       min(drawdown) drawdown
FROM dashboard.equity_snapshots GROUP BY mode,bucket
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS dashboard.equity_1h
WITH (timescaledb.continuous) AS
SELECT mode, time_bucket('1 hour', ts) bucket, last(equity,ts) equity,
       min(drawdown) drawdown
FROM dashboard.equity_snapshots GROUP BY mode,bucket
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS dashboard.equity_1d
WITH (timescaledb.continuous) AS
SELECT mode, time_bucket('1 day', ts) bucket, last(equity,ts) equity,
       min(drawdown) drawdown
FROM dashboard.equity_snapshots GROUP BY mode,bucket
WITH NO DATA;

CREATE INDEX IF NOT EXISTS idx_dash_equity_mode_ts ON dashboard.equity_snapshots(mode,ts DESC) INCLUDE(equity,drawdown,unrealized_pnl,today_pnl);
CREATE INDEX IF NOT EXISTS idx_dash_signal_symbol_ts ON dashboard.signal_events(symbol,ts DESC) INCLUDE(signal,price,indicators,mode);
CREATE INDEX IF NOT EXISTS idx_dash_diag_run_ts ON dashboard.model_diagnostics(run_id,ts DESC) INCLUDE(reward,policy_loss,value_loss,entropy);
CREATE INDEX IF NOT EXISTS idx_dash_bench_mode_end ON dashboard.benchmark_snapshots(mode,period_end DESC) INCLUDE(benchmark,total_return,sharpe,max_drawdown,trade_count);

-- Dashboard trade-log covering indexes: keyset pagination, not OFFSET.
CREATE INDEX IF NOT EXISTS idx_exec_orders_dash_cursor ON execution.orders(mode,update_time DESC,exchange_order_id DESC) INCLUDE(symbol,client_order_id,side,order_type,status,orig_qty,executed_qty,avg_price,latency_ms);
CREATE INDEX IF NOT EXISTS idx_exec_orders_dash_symbol ON execution.orders(mode,symbol,update_time DESC,exchange_order_id DESC) INCLUDE(side,status,executed_qty,avg_price);
CREATE INDEX IF NOT EXISTS idx_exec_fills_dash_time ON execution.fills(mode,trade_time DESC,exchange_trade_id DESC) INCLUDE(symbol,side,price,qty,quote_qty,commission);

-- Refresh policies: TimescaleDB serves the appropriate resolution instead of raw 1m for long ranges.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM timescaledb_information.jobs WHERE proc_name='policy_refresh_continuous_aggregate' AND hypertable_name='equity_5m') THEN
    PERFORM add_continuous_aggregate_policy('dashboard.equity_5m', start_offset => INTERVAL '7 days', end_offset => INTERVAL '1 minute', schedule_interval => INTERVAL '1 minute');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM timescaledb_information.jobs WHERE proc_name='policy_refresh_continuous_aggregate' AND hypertable_name='equity_1h') THEN
    PERFORM add_continuous_aggregate_policy('dashboard.equity_1h', start_offset => INTERVAL '90 days', end_offset => INTERVAL '5 minutes', schedule_interval => INTERVAL '5 minutes');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM timescaledb_information.jobs WHERE proc_name='policy_refresh_continuous_aggregate' AND hypertable_name='equity_1d') THEN
    PERFORM add_continuous_aggregate_policy('dashboard.equity_1d', start_offset => INTERVAL '3 years', end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '1 hour');
  END IF;
END $$;

-- Price continuous aggregates used by chart range selection.
CREATE MATERIALIZED VIEW IF NOT EXISTS market.klines_5m
WITH (timescaledb.continuous) AS
SELECT symbol, time_bucket('5 minutes', open_time) bucket,
       first(open,open_time) open, max(high) high, min(low) low,
       last(close,open_time) close, sum(volume) volume
FROM market.klines WHERE interval='1m' GROUP BY symbol,bucket WITH NO DATA;
CREATE MATERIALIZED VIEW IF NOT EXISTS market.klines_15m
WITH (timescaledb.continuous) AS
SELECT symbol, time_bucket('15 minutes', open_time) bucket,
       first(open,open_time) open, max(high) high, min(low) low,
       last(close,open_time) close, sum(volume) volume
FROM market.klines WHERE interval='1m' GROUP BY symbol,bucket WITH NO DATA;
CREATE MATERIALIZED VIEW IF NOT EXISTS market.klines_1h
WITH (timescaledb.continuous) AS
SELECT symbol, time_bucket('1 hour', open_time) bucket,
       first(open,open_time) open, max(high) high, min(low) low,
       last(close,open_time) close, sum(volume) volume
FROM market.klines WHERE interval='1m' GROUP BY symbol,bucket WITH NO DATA;
CREATE MATERIALIZED VIEW IF NOT EXISTS market.klines_1d
WITH (timescaledb.continuous) AS
SELECT symbol, time_bucket('1 day', open_time) bucket,
       first(open,open_time) open, max(high) high, min(low) low,
       last(close,open_time) close, sum(volume) volume
FROM market.klines WHERE interval='1m' GROUP BY symbol,bucket WITH NO DATA;

CREATE INDEX IF NOT EXISTS idx_klines_5m_dash ON market.klines_5m(symbol,bucket DESC);
CREATE INDEX IF NOT EXISTS idx_klines_15m_dash ON market.klines_15m(symbol,bucket DESC);
CREATE INDEX IF NOT EXISTS idx_klines_1h_dash ON market.klines_1h(symbol,bucket DESC);
CREATE INDEX IF NOT EXISTS idx_klines_1d_dash ON market.klines_1d(symbol,bucket DESC);

CREATE TABLE IF NOT EXISTS dashboard.metric_snapshots (
  mode TEXT NOT NULL,
  ts TIMESTAMPTZ NOT NULL,
  sharpe NUMERIC, sortino NUMERIC, calmar NUMERIC, max_drawdown NUMERIC,
  win_rate NUMERIC, profit_factor NUMERIC, expectancy NUMERIC,
  trade_count INTEGER, average_holding_minutes NUMERIC,
  PRIMARY KEY(mode,ts)
);
SELECT create_hypertable('dashboard.metric_snapshots','ts',if_not_exists=>TRUE,chunk_time_interval=>INTERVAL '30 days');
CREATE INDEX IF NOT EXISTS idx_dash_metric_mode_ts ON dashboard.metric_snapshots(mode,ts DESC) INCLUDE(sharpe,sortino,calmar,max_drawdown,win_rate,profit_factor,expectancy,trade_count,average_holding_minutes);

-- EXPLAIN ANALYZE verification queries are kept in docs/scripts and must be run against the deployed DB.
CREATE INDEX IF NOT EXISTS idx_exec_orders_dash_qty ON execution.orders(mode,executed_qty DESC,exchange_order_id DESC) INCLUDE(symbol,side,status,avg_price,update_time);
CREATE INDEX IF NOT EXISTS idx_exec_orders_dash_avg ON execution.orders(mode,avg_price DESC,exchange_order_id DESC) INCLUDE(symbol,side,status,executed_qty,update_time);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM timescaledb_information.jobs WHERE proc_name='policy_refresh_continuous_aggregate' AND hypertable_name='klines_5m') THEN
    PERFORM add_continuous_aggregate_policy('market.klines_5m', start_offset => INTERVAL '30 days', end_offset => INTERVAL '1 minute', schedule_interval => INTERVAL '1 minute');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM timescaledb_information.jobs WHERE proc_name='policy_refresh_continuous_aggregate' AND hypertable_name='klines_15m') THEN
    PERFORM add_continuous_aggregate_policy('market.klines_15m', start_offset => INTERVAL '90 days', end_offset => INTERVAL '5 minutes', schedule_interval => INTERVAL '5 minutes');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM timescaledb_information.jobs WHERE proc_name='policy_refresh_continuous_aggregate' AND hypertable_name='klines_1h') THEN
    PERFORM add_continuous_aggregate_policy('market.klines_1h', start_offset => INTERVAL '1 year', end_offset => INTERVAL '15 minutes', schedule_interval => INTERVAL '15 minutes');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM timescaledb_information.jobs WHERE proc_name='policy_refresh_continuous_aggregate' AND hypertable_name='klines_1d') THEN
    PERFORM add_continuous_aggregate_policy('market.klines_1d', start_offset => INTERVAL '3 years', end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '1 hour');
  END IF;
END $$;
