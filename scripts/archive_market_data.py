#!/usr/bin/env python3
"""Chunked, resumable raw-market archive to Parquet."""
from __future__ import annotations
import argparse, asyncio, hashlib, json, os
from datetime import datetime, timezone, timedelta
from pathlib import Path
import asyncpg, pandas as pd
RAW_TABLES={"trades_raw":"event_time","book_ticker":"event_time","ticker_24h":"event_time","mark_index_price":"event_time","open_interest":"event_time","top_trader_ratios":"event_time","liquidations":"event_time","orderbook_snapshots":"event_time","orderbook_updates":"event_time"}
async def archive(dsn,out,days,batch_size=10000):
 pool=await asyncpg.create_pool(dsn); cutoff=datetime.now(timezone.utc)-timedelta(days=days); out=Path(out);out.mkdir(parents=True,exist_ok=True); state_path=out/'.archive_checkpoints.json'; checkpoints=json.loads(state_path.read_text()) if state_path.exists() else {}
 try:
  async with pool.acquire() as c:
   for table,tscol in RAW_TABLES.items():
    checkpoint=checkpoints.get(table,{}); last_ts=checkpoint.get('last_ts'); last_ctid=checkpoint.get('last_ctid')
    last_ts_dt=datetime.fromisoformat(last_ts) if last_ts else None
    while True:
     q=f"SELECT ctid::text AS _ctid,* FROM market.{table} WHERE {tscol} < $1 AND ($2::timestamptz IS NULL OR ({tscol},ctid::text) > ($2::timestamptz,$3::text)) ORDER BY {tscol},ctid::text LIMIT $4"
     rows=await c.fetch(q,cutoff,last_ts_dt,last_ctid,batch_size)
     if not rows: break
     df=pd.DataFrame([dict(r) for r in rows]); ctids=df.pop('_ctid').tolist(); ts=pd.to_datetime(df[tscol],utc=True); first_ts=ts.iloc[0]; last_ts_value=ts.iloc[-1]
     digest=hashlib.sha256(('|'.join(ctids)).encode()).hexdigest()[:12]
     for month,part_df in df.groupby(ts.dt.to_period('M')):
      year=int(str(month)[:4]); mon=int(str(month)[5:7]); part=out/table/f"year={year:04d}/month={mon:02d}";part.mkdir(parents=True,exist_ok=True); path=part/f"archive_{first_ts.strftime('%Y%m%dT%H%M%S%fZ')}_{last_ts_value.strftime('%Y%m%dT%H%M%S%fZ')}_{digest}.parquet";part_df.to_parquet(path,index=False)
     await c.execute(f"DELETE FROM market.{table} WHERE ctid = ANY($1::tid[])",ctids)
     checkpoints[table]={'last_ts':last_ts_value.isoformat(),'last_ctid':ctids[-1],'updated_at':datetime.now(timezone.utc).isoformat()}; state_path.write_text(json.dumps(checkpoints,indent=2))
     last_ts_dt=last_ts_value; last_ctid=ctids[-1]
     print(f"archived {len(df)} rows from market.{table}")
 finally: await pool.close()
async def main():
 p=argparse.ArgumentParser();p.add_argument('--dsn',default=os.getenv('POSTGRES_DSN','postgresql://trader:trader@localhost:5432/crypto_rl'));p.add_argument('--days',type=int,default=int(os.getenv('ARCHIVE_AFTER_DAYS','60')));p.add_argument('--out',default=os.getenv('ARCHIVE_DIR','data/archive'));p.add_argument('--batch-size',type=int,default=10000);a=p.parse_args();await archive(a.dsn,a.out,a.days,a.batch_size)
if __name__=='__main__': asyncio.run(main())
