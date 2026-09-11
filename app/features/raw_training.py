"""Build and validate training frames from persisted raw Binance datasets."""
from __future__ import annotations

from datetime import datetime
import pandas as pd
from .microstructure import aggregate_trades
from .indicators import agg_trade_intensity
from .pipeline import FeaturePipeline


async def l2_coverage(pool, symbol: str, start: datetime, end: datetime) -> dict:
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """SELECT l2_history_start,l2_history_end,l2_coverage_percent
               FROM market.l2_coverage WHERE symbol=$1""", symbol.upper()
        )
    if not row:
        return {"available": False, "coverage_percent": 0.0}
    available = (row["l2_history_start"] is not None and row["l2_history_end"] is not None
                 and row["l2_history_start"] <= start and row["l2_history_end"] >= end
                 and float(row["l2_coverage_percent"] or 0.0) >= 100.0)
    # The per-symbol summary is useful telemetry, but exact-window row coverage
    # is authoritative: a broad start/end range can still contain a gap.
    expected = max(1, int((end - start).total_seconds() // 60))
    async with pool.acquire() as connection:
        count = await connection.fetchval(
            "SELECT count(*) FROM market.microstructure_1m WHERE symbol=$1 AND bucket >= $2 AND bucket < $3",
            symbol.upper(), start, end,
        )
    requested_percent = min(100.0, float(count or 0) * 100.0 / expected)
    available = bool(available and requested_percent >= 100.0)
    return {"available": available, "coverage_percent": requested_percent,
            "catalog_coverage_percent": float(row["l2_coverage_percent"] or 0.0),
            "start": row["l2_history_start"], "end": row["l2_history_end"]}


async def build_features_from_raw(pool, symbol: str, start: datetime, end: datetime,
                                  *, require_l2: bool = True) -> pd.DataFrame:
    coverage = await l2_coverage(pool, symbol, start, end)
    if require_l2 and not coverage["available"]:
        raise RuntimeError(
            f"incomplete L2 coverage for {symbol} {start.isoformat()}..{end.isoformat()}: "
            f"{coverage['coverage_percent']:.2f}%"
        )
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """SELECT k.open_time,k.open::float8 AS open,k.high::float8 AS high,k.low::float8 AS low,
                      k.close::float8 AS close,k.volume::float8 AS volume,
                      m.best_bid::float8,m.best_ask::float8,m.bid_qty::float8,m.ask_qty::float8,
                      m.microprice::float8,m.spread_abs::float8,m.spread_rel::float8,
                      m.trade_count::float8,m.trade_notional::float8,m.signed_volume::float8,
                      m.trade_intensity::float8,m.ofi::float8,m.kyle_lambda::float8
               FROM market.klines k
               LEFT JOIN market.microstructure_1m m ON m.symbol=k.symbol AND m.bucket=k.open_time
               WHERE k.symbol=$1 AND k.interval='1m' AND k.open_time >= $2 AND k.open_time <= $3
               ORDER BY k.open_time""", symbol.upper(), start, end
        )
        trades = await connection.fetch(
            """SELECT trade_time,agg_id,price::float8 AS price,quantity::float8 AS quantity,buyer_is_maker
               FROM market.trades_raw WHERE symbol=$1 AND trade_time >= $2 AND trade_time <= $3 ORDER BY trade_time""",
            symbol.upper(), start, end,
        )
    frame = pd.DataFrame([dict(row) for row in rows])
    if frame.empty:
        raise RuntimeError("raw reconstruction produced no 1m training rows")
    frame = frame.set_index("open_time").sort_index()
    if require_l2 and frame.filter(regex="^(best_bid|best_ask|microprice|spread_rel)$").isna().any().any():
        raise RuntimeError("microstructure reconstruction is incomplete for requested training window")
    raw_trades = pd.DataFrame([dict(row) for row in trades])
    if raw_trades.empty:
        raise RuntimeError("raw aggregate-trade reconstruction is incomplete for requested training window")
    trade_buckets = aggregate_trades(raw_trades).reindex(frame.index).fillna(0)
    for column in trade_buckets.columns: frame[column] = trade_buckets[column]
    frame["trade_intensity"] = agg_trade_intensity(frame.index, pd.to_datetime(raw_trades["trade_time"], utc=True), decay_seconds=60.0)
    # Recompute all causal technical features from the raw 1m bars.  The stored
    # L2/trade values are then joined as first-class feature inputs.
    technical = FeaturePipeline().compute(frame[["open","high","low","close","volume"]], fit_regime=True)
    frame = frame.join(technical, rsuffix="_technical")
    frame.attrs["microstructure_complete"] = bool(require_l2)
    frame.attrs["l2_coverage"] = coverage
    return frame
