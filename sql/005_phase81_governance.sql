CREATE SCHEMA IF NOT EXISTS governance;

CREATE TABLE IF NOT EXISTS governance.runtime_events (
  id BIGSERIAL PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  mode TEXT NOT NULL,
  event_type TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'INFO',
  reason TEXT,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_runtime_events_time ON governance.runtime_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runtime_events_type_time ON governance.runtime_events(event_type, created_at DESC);

CREATE TABLE IF NOT EXISTS governance.capital_ramp_audit (
  id BIGSERIAL PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  stage INTEGER NOT NULL,
  target_fraction DOUBLE PRECISION NOT NULL,
  approved_capital DOUBLE PRECISION NOT NULL,
  reviewer TEXT NOT NULL,
  human_signoff BOOLEAN NOT NULL,
  pnl_positive BOOLEAN NOT NULL DEFAULT FALSE,
  max_drawdown DOUBLE PRECISION NOT NULL DEFAULT 0,
  action TEXT NOT NULL CHECK(action IN ('INITIAL_ACTIVATION','ADVANCE','ROLLBACK'))
);
CREATE INDEX IF NOT EXISTS idx_capital_ramp_audit_time ON governance.capital_ramp_audit(created_at DESC);

CREATE TABLE IF NOT EXISTS governance.model_lifecycle (
  id BIGSERIAL PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  model_version TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('CHAMPION','CHALLENGER')),
  state TEXT NOT NULL,
  trigger TEXT,
  reviewer TEXT,
  human_signoff BOOLEAN NOT NULL DEFAULT FALSE,
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_model_lifecycle_version_time ON governance.model_lifecycle(model_version, created_at DESC);
