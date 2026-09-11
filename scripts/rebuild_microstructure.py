#!/usr/bin/env python3
"""Chunked historical L2 replay with a durable, restartable book-state checkpoint."""
from __future__ import annotations
import argparse, asyncio, json
import asyncpg
import pandas as pd
from app.features.microstructure import BookState, aggregate_trades
from app.features.indicators import agg_trade_intensity

def decode(levels):
    return {float(price): float(qty) for price, qty in (json.loads(levels) if isinstance(levels,str) else levels or [])}
def encode(levels): return [[price,qty] for price,qty in levels.items()]
def metrics(book):
    if not book.bids or not book.asks: return None
    bid=max(book.bids); ask=min(book.asks); bq=book.bids[bid]; aq=book.asks[ask]; mid=(bid+ask)/2
    return dict(best_bid=bid,best_ask=ask,bid_qty=bq,ask_qty=aq,microprice=(ask*bq+bid*aq)/(bq+aq) if bq+aq else mid,spread_abs=ask-bid,spread_rel=(ask-bid)/mid if mid else None)

async def load_state(pool,symbol,start,end):
    async with pool.acquire() as c:
        ck=await c.fetchrow("SELECT * FROM system.l2_rebuild_checkpoints WHERE symbol=$1 AND start_timestamp=$2 AND end_timestamp=$3",symbol,start,end)
        if ck and ck['completed']: return None,ck
        if ck and ck['book_bids'] is not None and ck['book_asks'] is not None:
            return BookState(decode(ck['book_bids']),decode(ck['book_asks']),int(ck['last_update_id'] or 0)),ck
        snap=await c.fetchrow("SELECT last_update_id,bids,asks FROM market.orderbook_snapshots WHERE symbol=$1 AND snapshot_time <= $2 ORDER BY snapshot_time DESC LIMIT 1",symbol,start)
    if not snap: raise RuntimeError(f"historical L2 unavailable for {symbol}: no snapshot at or before {start.isoformat()}")
    return BookState(decode(snap['bids']),decode(snap['asks']),int(snap['last_update_id'])),ck

async def persist_chunk(connection,symbol,start,end,book,last_bucket,cursor,rows,trade_rows):
    if rows:
        frame=pd.DataFrame(rows).sort_values('event_time'); frame['bucket']=pd.to_datetime(frame.event_time,utc=True).dt.floor('min')
        buckets=frame.groupby('bucket').last().reset_index()
        # Re-read complete minute buckets.  A diff-depth chunk can end halfway
        # through a minute, and using only its trades would make restart/upsert
        # results depend on chunk boundaries.
        first_bucket=buckets.bucket.min(); after_bucket=buckets.bucket.max()+pd.Timedelta(minutes=1)
        complete_trades=await connection.fetch("SELECT trade_time,agg_id,price::float8 AS price,quantity::float8 AS quantity,buyer_is_maker FROM market.trades_raw WHERE symbol=$1 AND trade_time >= $2 AND trade_time < $3 ORDER BY trade_time",symbol,first_bucket,after_bucket)
        trades=pd.DataFrame([dict(x) for x in complete_trades])
        if not trades.empty:
            grouped=aggregate_trades(trades).reindex(pd.DatetimeIndex(buckets.bucket),fill_value=0)
            intensity=agg_trade_intensity(pd.DatetimeIndex(buckets.bucket),pd.to_datetime(trades.trade_time,utc=True),decay_seconds=60.0)
        else:
            grouped=pd.DataFrame(index=pd.DatetimeIndex(buckets.bucket)); intensity=pd.Series(0.0,index=grouped.index)
        for index,row in buckets.iterrows():
            trade=grouped.loc[row.bucket] if row.bucket in grouped.index else {}
            await connection.execute("""INSERT INTO market.microstructure_1m(symbol,bucket,best_bid,best_ask,bid_qty,ask_qty,microprice,spread_abs,spread_rel,trade_count,trade_notional,signed_volume,trade_intensity)
              VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
              ON CONFLICT(symbol,bucket) DO UPDATE SET best_bid=EXCLUDED.best_bid,best_ask=EXCLUDED.best_ask,bid_qty=EXCLUDED.bid_qty,ask_qty=EXCLUDED.ask_qty,microprice=EXCLUDED.microprice,spread_abs=EXCLUDED.spread_abs,spread_rel=EXCLUDED.spread_rel,trade_count=EXCLUDED.trade_count,trade_notional=EXCLUDED.trade_notional,signed_volume=EXCLUDED.signed_volume,trade_intensity=EXCLUDED.trade_intensity""",
              symbol,row.bucket,row.best_bid,row.best_ask,row.bid_qty,row.ask_qty,row.microprice,row.spread_abs,row.spread_rel,
              int(trade.get('trade_count',0)),float(trade.get('trade_notional',0)),float(trade.get('signed_volume',0)),float(intensity.loc[row.bucket] if row.bucket in intensity.index else 0))
    await connection.execute("""INSERT INTO system.l2_rebuild_checkpoints(symbol,start_timestamp,end_timestamp,last_update_id,last_bucket,cursor_event_time,book_bids,book_asks,completed)
      VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,FALSE)
      ON CONFLICT(symbol,start_timestamp,end_timestamp) DO UPDATE SET last_update_id=EXCLUDED.last_update_id,last_bucket=EXCLUDED.last_bucket,cursor_event_time=EXCLUDED.cursor_event_time,book_bids=EXCLUDED.book_bids,book_asks=EXCLUDED.book_asks,completed=FALSE,updated_at=now()""",
      symbol,start,end,book.last_update_id,last_bucket,cursor,json.dumps(encode(book.bids)),json.dumps(encode(book.asks)))

async def run(dsn,symbol,start,end,out=None,write_db=False,chunk_size=10000):
    pool=await asyncpg.create_pool(dsn); symbol=symbol.upper()
    try:
      book,checkpoint=await load_state(pool,symbol,start,end)
      if book is None: return pd.DataFrame()
      cursor=checkpoint['cursor_event_time'] if checkpoint and checkpoint['cursor_event_time'] else start
      previous_cursor=cursor; all_output=[]
      while cursor < end:
        async with pool.acquire() as c:
          updates=await c.fetch("""SELECT event_time,first_update_id,final_update_id,bids,asks FROM market.orderbook_updates
            WHERE symbol=$1 AND event_time >= $2 AND event_time < $3 AND final_update_id > $4 ORDER BY event_time,final_update_id LIMIT $5""",symbol,cursor,end,book.last_update_id,chunk_size)
          if not updates: break
          # Keep equal-timestamp updates eligible; final_update_id advances the cursor.
          next_cursor=updates[-1]['event_time']
          rows=[]
          for update in updates:
            # Apply a Binance diff-depth update atomically as bid/ask level arrays.
            book.apply(update['bids'],update['asks'],update['final_update_id'])
            value=metrics(book)
            if value: rows.append({'event_time':update['event_time'],**value})
          last_bucket=pd.Timestamp(rows[-1]['event_time']).floor('min') if rows else checkpoint['last_bucket'] if checkpoint else None
          async with c.transaction(): await persist_chunk(c,symbol,start,end,book,last_bucket,next_cursor,rows,[])
          all_output.extend(rows); previous_cursor=next_cursor; cursor=next_cursor
      async with pool.acquire() as c:
        history=await c.fetchrow("SELECT min(bucket) AS first_bucket,max(bucket) AS last_bucket,count(*) AS count FROM market.microstructure_1m WHERE symbol=$1",symbol)
        history_start=history['first_bucket']; history_end=history['last_bucket']+pd.Timedelta(minutes=1) if history['last_bucket'] else None
        expected=max(1,int((history_end-history_start).total_seconds()//60)) if history_start and history_end else 1
        coverage=min(100.0,float(history['count'] or 0)*100/expected)
        await c.execute("""INSERT INTO market.l2_coverage(symbol,l2_history_start,l2_history_end,l2_coverage_percent) VALUES($1,$2,$3,$4)
          ON CONFLICT(symbol) DO UPDATE SET l2_history_start=EXCLUDED.l2_history_start,l2_history_end=EXCLUDED.l2_history_end,l2_coverage_percent=EXCLUDED.l2_coverage_percent,updated_at=now()""",symbol,history_start,history_end,coverage)
        await c.execute("UPDATE system.l2_rebuild_checkpoints SET completed=TRUE,updated_at=now() WHERE symbol=$1 AND start_timestamp=$2 AND end_timestamp=$3",symbol,start,end)
      output=pd.DataFrame(all_output)
      if out and not output.empty: output.to_parquet(out)
      return output
    finally: await pool.close()

async def main():
 p=argparse.ArgumentParser();p.add_argument('--dsn',required=True);p.add_argument('--symbol',required=True);p.add_argument('--start',required=True);p.add_argument('--end',required=True);p.add_argument('--out');p.add_argument('--chunk-size',type=int,default=10000);a=p.parse_args(); await run(a.dsn,a.symbol,pd.Timestamp(a.start),pd.Timestamp(a.end),a.out,True,a.chunk_size)
if __name__=='__main__': asyncio.run(main())
