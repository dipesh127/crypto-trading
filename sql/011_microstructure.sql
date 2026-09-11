CREATE TABLE IF NOT EXISTS market.microstructure_1m (
 symbol TEXT NOT NULL, bucket TIMESTAMPTZ NOT NULL, best_bid NUMERIC, best_ask NUMERIC, bid_qty NUMERIC, ask_qty NUMERIC, microprice NUMERIC, spread_abs NUMERIC, spread_rel NUMERIC,
 trade_count BIGINT, trade_notional NUMERIC, signed_volume NUMERIC, trade_intensity NUMERIC, ofi NUMERIC, kyle_lambda NUMERIC,
 depth_bid_1bps NUMERIC,depth_ask_1bps NUMERIC,depth_bid_5bps NUMERIC,depth_ask_5bps NUMERIC,depth_bid_10bps NUMERIC,depth_ask_10bps NUMERIC,depth_bid_25bps NUMERIC,depth_ask_25bps NUMERIC,depth_bid_50bps NUMERIC,depth_ask_50bps NUMERIC,
 liq_long NUMERIC, liq_short NUMERIC, PRIMARY KEY(symbol,bucket)
);
SELECT create_hypertable('market.microstructure_1m','bucket',if_not_exists=>TRUE,chunk_time_interval=>INTERVAL '7 days');
CREATE INDEX IF NOT EXISTS idx_microstructure_symbol_bucket ON market.microstructure_1m(symbol,bucket DESC);
