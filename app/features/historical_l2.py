"""Composable primitives for chronological, resumable historical L2 reconstruction."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator


@dataclass(frozen=True)
class L2ResumeState:
    symbol: str
    start_timestamp: datetime
    end_timestamp: datetime
    last_update_id: int | None = None
    last_bucket: datetime | None = None


class HistoricalSnapshotLoader:
    def __init__(self, pool): self.pool=pool
    async def load(self, symbol, start):
        async with self.pool.acquire() as c:
            return await c.fetchrow("SELECT snapshot_time,last_update_id,bids,asks FROM market.orderbook_snapshots WHERE symbol=$1 AND snapshot_time <= $2 ORDER BY snapshot_time DESC LIMIT 1",symbol,start)


class DepthUpdateChunkReader:
    def __init__(self, pool, chunk_size=10000): self.pool=pool; self.chunk_size=int(chunk_size)
    async def read(self, symbol, start, end, after_update_id=0) -> AsyncIterator[list]:
        cursor=start; latest=int(after_update_id or 0)
        while cursor < end:
            async with self.pool.acquire() as c:
                rows=await c.fetch("SELECT event_time,first_update_id,final_update_id,bids,asks FROM market.orderbook_updates WHERE symbol=$1 AND event_time >= $2 AND event_time < $3 AND final_update_id > $4 ORDER BY event_time,final_update_id LIMIT $5",symbol,cursor,end,latest,self.chunk_size)
            if not rows: return
            yield rows
            latest=max(int(r['final_update_id']) for r in rows)
            cursor=rows[-1]['event_time']


class OrderBookReplayEngine:
    """Stateful replay engine; callers checkpoint ``last_update_id`` after each chunk."""
    def __init__(self, book): self.book=book
    def apply_chunk(self, updates):
        samples=[]
        for row in updates:
            self.book.apply(row['bids'], row['asks'], row['final_update_id'])
            samples.append((row['event_time'], self.book))
        return samples


class MicrostructureBucketWriter:
    def __init__(self, pool): self.pool=pool
    async def checkpoint(self, state: L2ResumeState, *, completed=False):
        async with self.pool.acquire() as c:
            await c.execute("INSERT INTO system.l2_rebuild_checkpoints(symbol,start_timestamp,end_timestamp,last_update_id,last_bucket,completed) VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(symbol,start_timestamp,end_timestamp) DO UPDATE SET last_update_id=EXCLUDED.last_update_id,last_bucket=EXCLUDED.last_bucket,completed=EXCLUDED.completed,updated_at=now()",state.symbol,state.start_timestamp,state.end_timestamp,state.last_update_id,state.last_bucket,completed)

    async def write_bucket(self, symbol, bucket, values):
        """Idempotently persist one replayed minute; safe to repeat after restart."""
        async with self.pool.acquire() as c:
            await c.execute(
                """INSERT INTO market.microstructure_1m(symbol,bucket,best_bid,best_ask,bid_qty,ask_qty,microprice,spread_abs,spread_rel,trade_count,trade_notional,signed_volume,trade_intensity)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                ON CONFLICT(symbol,bucket) DO UPDATE SET best_bid=EXCLUDED.best_bid,best_ask=EXCLUDED.best_ask,bid_qty=EXCLUDED.bid_qty,ask_qty=EXCLUDED.ask_qty,microprice=EXCLUDED.microprice,spread_abs=EXCLUDED.spread_abs,spread_rel=EXCLUDED.spread_rel,trade_count=EXCLUDED.trade_count,trade_notional=EXCLUDED.trade_notional,signed_volume=EXCLUDED.signed_volume,trade_intensity=EXCLUDED.trade_intensity""",
                symbol, bucket, values.get('best_bid'), values.get('best_ask'), values.get('bid_qty'), values.get('ask_qty'), values.get('microprice'), values.get('spread_abs'), values.get('spread_rel'), int(values.get('trade_count', 0)), float(values.get('trade_notional', 0)), float(values.get('signed_volume', 0)), float(values.get('trade_intensity', 0)),
            )
