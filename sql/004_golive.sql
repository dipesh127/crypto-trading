CREATE SCHEMA IF NOT EXISTS governance;

CREATE TABLE IF NOT EXISTS governance.go_live_reviews (
  id BIGSERIAL PRIMARY KEY,
  reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  reviewer_name TEXT NOT NULL,
  evidence_digest TEXT NOT NULL,
  paper_start TIMESTAMPTZ NOT NULL,
  paper_end TIMESTAMPTZ NOT NULL,
  profitable_weeks INTEGER NOT NULL,
  trade_count INTEGER NOT NULL,
  max_drawdown DOUBLE PRECISION NOT NULL,
  market_regimes TEXT[] NOT NULL,
  risk_controls_tested BOOLEAN NOT NULL,
  human_signoff BOOLEAN NOT NULL,
  authorized BOOLEAN NOT NULL,
  security_attestation JSONB NOT NULL DEFAULT '{}'::jsonb,
  notes TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_go_live_reviews_time ON governance.go_live_reviews(reviewed_at DESC);
CREATE INDEX IF NOT EXISTS idx_go_live_reviews_digest ON governance.go_live_reviews(evidence_digest);

CREATE TABLE IF NOT EXISTS governance.capital_ramp (
  mode TEXT NOT NULL,
  stage INTEGER NOT NULL,
  target_fraction DOUBLE PRECISION NOT NULL,
  activated_at TIMESTAMPTZ,
  deactivated_at TIMESTAMPTZ,
  pnl_positive BOOLEAN NOT NULL DEFAULT FALSE,
  max_drawdown DOUBLE PRECISION,
  reviewer_name TEXT,
  human_approved BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY(mode,stage)
);

CREATE TABLE IF NOT EXISTS governance.champion_challenger_reviews (
  id BIGSERIAL PRIMARY KEY,
  reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  challenger_version TEXT NOT NULL,
  champion_version TEXT NOT NULL,
  paper_metrics JSONB NOT NULL,
  drift_metrics JSONB NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('RETAIN_CHAMPION','PROMOTE_CHALLENGER','REJECT_CHALLENGER')),
  reviewer_name TEXT NOT NULL,
  human_signoff BOOLEAN NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_challenger_reviews_time ON governance.champion_challenger_reviews(reviewed_at DESC);
