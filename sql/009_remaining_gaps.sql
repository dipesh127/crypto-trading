-- Remaining-gap support: metric history, monitoring, and explicit execution configuration.
CREATE SCHEMA IF NOT EXISTS dashboard;
CREATE INDEX IF NOT EXISTS idx_metric_snapshots_mode_ts ON dashboard.metric_snapshots(mode,ts DESC);
-- Keep dashboard metric history bounded while preserving longer-term aggregates.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM timescaledb_information.jobs WHERE hypertable_name='metric_snapshots' AND proc_name='policy_retention') THEN
    PERFORM add_retention_policy('dashboard.metric_snapshots', INTERVAL '3 years', if_not_exists => TRUE);
  END IF;
EXCEPTION WHEN undefined_function THEN NULL; END $$;

CREATE INDEX IF NOT EXISTS idx_trades_symbol_time ON market.trades_raw(symbol,event_time DESC);
CREATE INDEX IF NOT EXISTS idx_ticker_symbol_time ON market.ticker_24h(symbol,event_time DESC);
