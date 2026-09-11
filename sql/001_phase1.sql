CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE SCHEMA IF NOT EXISTS market;
CREATE SCHEMA IF NOT EXISTS system;

CREATE TABLE IF NOT EXISTS market.klines (
  symbol TEXT NOT NULL, interval TEXT NOT NULL, open_time TIMESTAMPTZ NOT NULL,
  close_time TIMESTAMPTZ NOT NULL, open NUMERIC NOT NULL, high NUMERIC NOT NULL,
  low NUMERIC NOT NULL, close NUMERIC NOT NULL, volume NUMERIC NOT NULL,
  quote_volume NUMERIC NOT NULL, trade_count BIGINT NOT NULL,
  taker_buy_base_volume NUMERIC NOT NULL, taker_buy_quote_volume NUMERIC NOT NULL,
  first_trade_id BIGINT, last_trade_id BIGINT, event_time TIMESTAMPTZ,
  is_closed BOOLEAN NOT NULL DEFAULT TRUE,
  PRIMARY KEY(symbol,interval,open_time)
);
SELECT create_hypertable('market.klines','open_time',if_not_exists=>TRUE,chunk_time_interval=>INTERVAL '7 days');

CREATE TABLE IF NOT EXISTS market.trades_raw (
  symbol TEXT NOT NULL, event_time TIMESTAMPTZ NOT NULL, trade_time TIMESTAMPTZ NOT NULL,
  agg_id BIGINT NOT NULL, price NUMERIC NOT NULL, quantity NUMERIC NOT NULL,
  first_trade_id BIGINT, last_trade_id BIGINT, buyer_is_maker BOOLEAN NOT NULL,
  source TEXT NOT NULL DEFAULT 'websocket', PRIMARY KEY(symbol,agg_id)
);
SELECT create_hypertable('market.trades_raw','event_time',if_not_exists=>TRUE,chunk_time_interval=>INTERVAL '1 day');

CREATE TABLE IF NOT EXISTS market.book_ticker (
  symbol TEXT NOT NULL, event_time TIMESTAMPTZ NOT NULL, transaction_time TIMESTAMPTZ,
  update_id BIGINT NOT NULL, bid_price NUMERIC NOT NULL, bid_qty NUMERIC NOT NULL,
  ask_price NUMERIC NOT NULL, ask_qty NUMERIC NOT NULL,
  PRIMARY KEY(symbol,update_id)
);
SELECT create_hypertable('market.book_ticker','event_time',if_not_exists=>TRUE,chunk_time_interval=>INTERVAL '1 day');


CREATE TABLE IF NOT EXISTS market.ticker_24h (
  symbol TEXT NOT NULL, event_time TIMESTAMPTZ NOT NULL, transaction_time TIMESTAMPTZ, update_id BIGINT NOT NULL,
  price_change NUMERIC, price_change_percent NUMERIC, weighted_avg_price NUMERIC, last_price NUMERIC, last_qty NUMERIC,
  open_price NUMERIC, high_price NUMERIC, low_price NUMERIC, volume NUMERIC, quote_volume NUMERIC,
  open_time TIMESTAMPTZ, close_time TIMESTAMPTZ, first_trade_id BIGINT, last_trade_id BIGINT, trade_count BIGINT, raw JSONB NOT NULL,
  PRIMARY KEY(symbol,update_id)
);
SELECT create_hypertable('market.ticker_24h','event_time',if_not_exists=>TRUE,chunk_time_interval=>INTERVAL '1 day');

CREATE TABLE IF NOT EXISTS market.mark_index_price (
  symbol TEXT NOT NULL, event_time TIMESTAMPTZ NOT NULL, transaction_time TIMESTAMPTZ,
  mark_price NUMERIC NOT NULL, index_price NUMERIC NOT NULL,
  estimated_settle_price NUMERIC, funding_rate NUMERIC, next_funding_time TIMESTAMPTZ,
  PRIMARY KEY(symbol,event_time)
);
SELECT create_hypertable('market.mark_index_price','event_time',if_not_exists=>TRUE,chunk_time_interval=>INTERVAL '1 day');

CREATE TABLE IF NOT EXISTS market.funding_rates (
  symbol TEXT NOT NULL, funding_time TIMESTAMPTZ NOT NULL,
  funding_rate NUMERIC NOT NULL, mark_price NUMERIC,
  PRIMARY KEY(symbol,funding_time)
);
SELECT create_hypertable('market.funding_rates','funding_time',if_not_exists=>TRUE,chunk_time_interval=>INTERVAL '30 days');

CREATE TABLE IF NOT EXISTS market.open_interest (
  symbol TEXT NOT NULL, event_time TIMESTAMPTZ NOT NULL, open_interest NUMERIC NOT NULL,
  open_interest_value NUMERIC, source TEXT NOT NULL,
  PRIMARY KEY(symbol,event_time,source)
);
SELECT create_hypertable('market.open_interest','event_time',if_not_exists=>TRUE,chunk_time_interval=>INTERVAL '7 days');

CREATE TABLE IF NOT EXISTS market.top_trader_ratios (
  symbol TEXT NOT NULL, event_time TIMESTAMPTZ NOT NULL, period TEXT NOT NULL,
  long_short_ratio NUMERIC NOT NULL, long_account NUMERIC NOT NULL,
  short_account NUMERIC NOT NULL, source TEXT NOT NULL,
  PRIMARY KEY(symbol,event_time,period,source)
);
SELECT create_hypertable('market.top_trader_ratios','event_time',if_not_exists=>TRUE,chunk_time_interval=>INTERVAL '7 days');

CREATE TABLE IF NOT EXISTS market.liquidations (
  symbol TEXT NOT NULL, event_time TIMESTAMPTZ NOT NULL, transaction_time TIMESTAMPTZ,
  side TEXT NOT NULL, order_type TEXT, time_in_force TEXT,
  original_quantity NUMERIC, price NUMERIC, average_price NUMERIC,
  last_filled_quantity NUMERIC, filled_accumulated_quantity NUMERIC,
  status TEXT, execution_type TEXT, source TEXT NOT NULL DEFAULT 'websocket',
  PRIMARY KEY(symbol,event_time,transaction_time,side,execution_type)
);
SELECT create_hypertable('market.liquidations','event_time',if_not_exists=>TRUE,chunk_time_interval=>INTERVAL '1 day');

CREATE TABLE IF NOT EXISTS market.orderbook_snapshots (
  symbol TEXT NOT NULL, event_time TIMESTAMPTZ NOT NULL, snapshot_time TIMESTAMPTZ NOT NULL,
  last_update_id BIGINT NOT NULL, bids JSONB NOT NULL, asks JSONB NOT NULL,
  depth_limit INTEGER NOT NULL, checksum_ok BOOLEAN, source TEXT NOT NULL DEFAULT 'rest_snapshot',
  PRIMARY KEY(symbol,snapshot_time)
);
SELECT create_hypertable('market.orderbook_snapshots','event_time',if_not_exists=>TRUE,chunk_time_interval=>INTERVAL '1 day');

CREATE TABLE IF NOT EXISTS market.orderbook_updates (
  symbol TEXT NOT NULL, event_time TIMESTAMPTZ NOT NULL,
  first_update_id BIGINT NOT NULL, final_update_id BIGINT NOT NULL,
  prev_final_update_id BIGINT, bids JSONB NOT NULL, asks JSONB NOT NULL,
  applied BOOLEAN NOT NULL DEFAULT FALSE, quality_flag TEXT NOT NULL DEFAULT 'OK',
  PRIMARY KEY(symbol,event_time,first_update_id,final_update_id)
);
SELECT create_hypertable('market.orderbook_updates','event_time',if_not_exists=>TRUE,chunk_time_interval=>INTERVAL '1 day');

CREATE TABLE IF NOT EXISTS market.exchange_info (
  symbol TEXT PRIMARY KEY, status TEXT NOT NULL, base_asset TEXT NOT NULL,
  quote_asset TEXT NOT NULL, contract_type TEXT, price_precision INTEGER,
  quantity_precision INTEGER, tick_size NUMERIC, step_size NUMERIC,
  min_qty NUMERIC, min_notional NUMERIC, raw JSONB NOT NULL,
  observed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS market.leverage_brackets (
  symbol TEXT NOT NULL, bracket INTEGER NOT NULL, initial_leverage INTEGER NOT NULL,
  notional_floor NUMERIC NOT NULL, notional_cap NUMERIC NOT NULL,
  maint_margin_ratio NUMERIC NOT NULL, cum NUMERIC NOT NULL,
  notional_coef NUMERIC, observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY(symbol,bracket)
);

CREATE TABLE IF NOT EXISTS system.data_quality_events (
  id BIGSERIAL PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  symbol TEXT, data_type TEXT NOT NULL, event_time TIMESTAMPTZ,
  quality_flag TEXT NOT NULL, details JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS system.server_time_sync (
  observed_at TIMESTAMPTZ NOT NULL, server_time_ms BIGINT NOT NULL,
  local_time_ms BIGINT NOT NULL, offset_ms BIGINT NOT NULL
);
SELECT create_hypertable('system.server_time_sync','observed_at',if_not_exists=>TRUE,chunk_time_interval=>INTERVAL '30 days');

CREATE INDEX IF NOT EXISTS idx_klines_symbol_time
ON market.klines(symbol,interval,open_time DESC);
CREATE INDEX IF NOT EXISTS idx_quality_symbol_time
ON system.data_quality_events(symbol,created_at DESC);

CREATE INDEX IF NOT EXISTS idx_trades_symbol_time ON market.trades_raw(symbol,event_time DESC);
CREATE INDEX IF NOT EXISTS idx_ticker_symbol_time ON market.ticker_24h(symbol,event_time DESC);
