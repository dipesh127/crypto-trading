-- Persistent historical-L2 coverage and resumable replay state.
CREATE TABLE IF NOT EXISTS market.l2_coverage (
  symbol TEXT PRIMARY KEY,
  l2_history_start TIMESTAMPTZ,
  l2_history_end TIMESTAMPTZ,
  l2_coverage_percent DOUBLE PRECISION NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS system.l2_rebuild_checkpoints (
  symbol TEXT NOT NULL,
  start_timestamp TIMESTAMPTZ NOT NULL,
  end_timestamp TIMESTAMPTZ NOT NULL,
  last_update_id BIGINT,
  last_bucket TIMESTAMPTZ,
  cursor_event_time TIMESTAMPTZ,
  book_bids JSONB,
  book_asks JSONB,
  completed BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY(symbol,start_timestamp,end_timestamp)
);

ALTER TABLE system.l2_rebuild_checkpoints ADD COLUMN IF NOT EXISTS cursor_event_time TIMESTAMPTZ;
ALTER TABLE system.l2_rebuild_checkpoints ADD COLUMN IF NOT EXISTS book_bids JSONB;
ALTER TABLE system.l2_rebuild_checkpoints ADD COLUMN IF NOT EXISTS book_asks JSONB;

CREATE INDEX IF NOT EXISTS idx_l2_coverage_window
  ON market.l2_coverage(symbol,l2_history_start,l2_history_end);
