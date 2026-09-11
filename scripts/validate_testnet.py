import asyncio
from app.config import get_settings
from app.binance import BinanceREST

async def main():
    s=get_settings()
    c=BinanceREST(s.binance_rest_base_url,s.binance_api_key,s.binance_api_secret,s.binance_recv_window_ms)
    await c.start()
    try:
        print("server offset:",await c.sync_server_time(),"ms")
        info=await c.exchange_info(); print("exchangeInfo symbols:",len(info["symbols"]))
        for sym in s.symbol_list:
            d=await c.depth(sym,min(s.orderbook_depth_limit,1000))
            print(sym,"depth lastUpdateId:",d["lastUpdateId"])
            if s.binance_api_key and s.binance_api_secret:
                print(sym,"leverage brackets:",len((await c.leverage_bracket(sym))[0]["brackets"]))
    finally: await c.close()
if __name__=="__main__": asyncio.run(main())
