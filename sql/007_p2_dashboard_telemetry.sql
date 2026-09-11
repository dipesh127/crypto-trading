-- Phase 2 dashboard telemetry: durable account/margin snapshots and funding metadata.
CREATE SCHEMA IF NOT EXISTS dashboard;

CREATE TABLE IF NOT EXISTS dashboard.account_snapshots (
  mode TEXT NOT NULL,
  ts TIMESTAMPTZ NOT NULL,
  wallet_balance NUMERIC,
  available_balance NUMERIC,
  equity NUMERIC,
  unrealized_pnl NUMERIC,
  total_initial_margin NUMERIC,
  total_maint_margin NUMERIC,
  margin_ratio NUMERIC,
  leverage NUMERIC,
  today_pnl NUMERIC,
  positions JSONB NOT NULL DEFAULT '[]'::jsonb,
  PRIMARY KEY(mode, ts)
);
SELECT create_hypertable('dashboard.account_snapshots','ts',if_not_exists=>TRUE,chunk_time_interval=>INTERVAL '30 days');
CREATE INDEX IF NOT EXISTS idx_dash_account_mode_ts
  ON dashboard.account_snapshots(mode,ts DESC)
  INCLUDE(wallet_balance,available_balance,equity,unrealized_pnl,total_initial_margin,total_maint_margin,margin_ratio,leverage,today_pnl);
ALTER TABLE dashboard.account_snapshots ADD COLUMN IF NOT EXISTS positions JSONB NOT NULL DEFAULT '[]'::jsonb;

-- The dashboard derives the current funding countdown from Binance's mark/index stream,
-- while historical funding remains in market.funding_rates.
CREATE INDEX IF NOT EXISTS idx_market_mark_index_symbol_time
  ON market.mark_index_price(symbol,event_time DESC)
  INCLUDE(mark_price,index_price,funding_rate,next_funding_time);
CREATE INDEX IF NOT EXISTS idx_market_funding_symbol_time
  ON market.funding_rates(symbol,funding_time DESC)
  INCLUDE(funding_rate,mark_price);
