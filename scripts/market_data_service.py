#!/usr/bin/env python3
import asyncio, asyncpg
from redis import asyncio as redis_asyncio
from app.config import get_settings
from app.binance import BinanceREST
from app.market_data import MarketDataIngestion

async def main():
    s=get_settings(); pool=await asyncpg.create_pool(s.postgres_dsn); redis=redis_asyncio.from_url(s.redis_url,decode_responses=True)
    rest=BinanceREST(s.binance_rest_base_url,s.binance_api_key,s.binance_api_secret,s.binance_recv_window_ms,s.binance_ws_base_url); await rest.start()
    ing=MarketDataIngestion(s,rest,pool,redis)
    try:
        await ing.bootstrap(); await ing.start(); await asyncio.Event().wait()
    finally:
        await ing.stop_service(); await rest.close(); await redis.aclose(); await pool.close()
if __name__=="__main__": asyncio.run(main())
