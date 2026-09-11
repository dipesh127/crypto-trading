#!/usr/bin/env python3
"""Explicit months-long Binance USD-M market-data backfill."""
from __future__ import annotations
import argparse, asyncio, asyncpg
from app.config import get_settings
from app.binance import BinanceREST
from app.market_data import MarketDataIngestion
from redis import asyncio as redis_asyncio

async def main():
    p=argparse.ArgumentParser(); p.add_argument('--days',type=int,default=None); p.add_argument('--symbols',default=None); p.add_argument('--batch',type=int,default=1000); a=p.parse_args()
    s=get_settings(); symbols=[x.strip().upper() for x in a.symbols.split(',') if x.strip()] if a.symbols else s.symbol_list
    old=s.symbols; s.symbols=','.join(symbols)
    pool=await asyncpg.create_pool(s.postgres_dsn); redis=redis_asyncio.from_url(s.redis_url,decode_responses=True); rest=BinanceREST(s.binance_rest_base_url,s.binance_api_key,s.binance_api_secret,s.binance_recv_window_ms,s.binance_ws_base_url); await rest.start()
    try:
        ing=MarketDataIngestion(s,rest,pool,redis); await ing.bootstrap() if a.days is None else asyncio.gather(*(ing.backfill_symbol(sym,days=a.days,batch_limit=a.batch) for sym in symbols))
    finally:
        await rest.close(); await redis.close(); await pool.close()
if __name__=='__main__': asyncio.run(main())
