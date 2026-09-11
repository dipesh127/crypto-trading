import asyncio, logging
import asyncpg
from redis import asyncio as redis_asyncio
from .config import get_settings
from .binance import BinanceREST
from .market_data import MarketDataIngestion

async def main():
    s=get_settings(); logging.basicConfig(level=s.log_level)
    pool=await asyncpg.create_pool(s.postgres_dsn)
    redis=redis_asyncio.from_url(s.redis_url,decode_responses=True)
    rest=BinanceREST(s.binance_rest_base_url,s.binance_api_key,s.binance_api_secret,s.binance_recv_window_ms,s.binance_ws_base_url,
                     raw_requests_per_minute=s.binance_raw_requests_per_minute,
                     order_requests_per_minute=s.binance_order_requests_per_minute,
                     weight_per_minute=s.binance_weight_per_minute,state_store=redis)
    await rest.start()
    service=MarketDataIngestion(s,rest,pool,redis)
    try:
        await service.bootstrap()
        await service.start()
        logging.info("market ingestion started: symbols=%s intervals=%s",s.symbol_list,s.interval_list)
        await service.ws_task
    finally:
        await service.stop_service()
        await rest.close()
        await redis.aclose()
        await pool.close()

if __name__=="__main__": asyncio.run(main())
