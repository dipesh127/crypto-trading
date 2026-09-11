-- Durable authenticated user-data websocket health for dashboard connection telemetry.
CREATE SCHEMA IF NOT EXISTS dashboard;
CREATE TABLE IF NOT EXISTS dashboard.ws_health (
  mode TEXT NOT NULL,
  ts TIMESTAMPTZ NOT NULL,
  connected BOOLEAN NOT NULL,
  last_event_time TIMESTAMPTZ,
  last_error TEXT
);
SELECT create_hypertable('dashboard.ws_health','ts',if_not_exists=>TRUE,chunk_time_interval=>INTERVAL '7 days');
CREATE INDEX IF NOT EXISTS idx_dash_ws_health_mode_ts ON dashboard.ws_health(mode,ts DESC);
