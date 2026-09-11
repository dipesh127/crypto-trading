-- Urgent hardening: persistent position open-time and resumable backfill state.
CREATE TABLE IF NOT EXISTS execution.position_lifecycle (
  mode TEXT NOT NULL, symbol TEXT NOT NULL, opened_at_ms BIGINT, open_time_known BOOLEAN NOT NULL DEFAULT TRUE, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY(mode,symbol)
);
CREATE TABLE IF NOT EXISTS system.backfill_checkpoints (
  symbol TEXT NOT NULL, dataset TEXT NOT NULL, interval TEXT NOT NULL DEFAULT '',
  cursor_text TEXT NOT NULL DEFAULT '', cursor_ms BIGINT, cursor_id BIGINT, completed BOOLEAN NOT NULL DEFAULT FALSE, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY(symbol,dataset,interval)
);
CREATE INDEX IF NOT EXISTS idx_backfill_checkpoint_updated ON system.backfill_checkpoints(updated_at DESC);

ALTER TABLE execution.position_lifecycle ADD COLUMN IF NOT EXISTS open_time_known BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE execution.position_lifecycle ALTER COLUMN opened_at_ms DROP NOT NULL;
