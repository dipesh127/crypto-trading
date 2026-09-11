-- Phase P0 migration for existing databases. Safe to run repeatedly.
CREATE TABLE IF NOT EXISTS market.ticker_24h (
  symbol TEXT NOT NULL, event_time TIMESTAMPTZ NOT NULL, transaction_time TIMESTAMPTZ, update_id BIGINT NOT NULL,
  price_change NUMERIC, price_change_percent NUMERIC, weighted_avg_price NUMERIC, last_price NUMERIC, last_qty NUMERIC,
  open_price NUMERIC, high_price NUMERIC, low_price NUMERIC, volume NUMERIC, quote_volume NUMERIC,
  open_time TIMESTAMPTZ, close_time TIMESTAMPTZ, first_trade_id BIGINT, last_trade_id BIGINT, trade_count BIGINT, raw JSONB NOT NULL,
  PRIMARY KEY(symbol,update_id)
);
SELECT create_hypertable('market.ticker_24h','event_time',if_not_exists=>TRUE,chunk_time_interval=>INTERVAL '1 day');
CREATE INDEX IF NOT EXISTS idx_ticker_symbol_time ON market.ticker_24h(symbol,event_time DESC);
