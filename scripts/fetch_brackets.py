import asyncio, json
from app.config import get_settings
from app.binance import BinanceREST
async def main():
 s=get_settings(); c=BinanceREST(s.binance_rest_base_url,s.binance_api_key,s.binance_api_secret,s.binance_recv_window_ms); await c.start()
 try:
  if not s.binance_api_key or not s.binance_api_secret: raise SystemExit('API credentials are required for signed /fapi/v1/leverageBracket')
  out={x:await c.leverage_bracket(x) for x in s.symbol_list}; print(json.dumps(out,indent=2))
 finally: await c.close()
if __name__=='__main__': asyncio.run(main())
