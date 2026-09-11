#!/usr/bin/env python3
import argparse, asyncio, logging
from app.config import get_settings
from app.binance import BinanceREST
from app.paper import BinancePaperExecutionAdapter
from app.reconciliation import Reconciler

async def main():
    p=argparse.ArgumentParser(); p.add_argument('--symbol',action='append',required=True); a=p.parse_args(); s=get_settings()
    if s.app_env.lower()!='testnet': raise SystemExit('Refusing reconciliation from this Phase 5 command unless APP_ENV=testnet')
    rest=BinanceREST(s.binance_rest_base_url,s.binance_api_key,s.binance_api_secret,s.binance_recv_window_ms,s.binance_ws_base_url)
    await rest.start(); adapter=BinancePaperExecutionAdapter(rest)
    try:
        await adapter.bootstrap_state()
        r=Reconciler(adapter)
        print(await r.check(a.symbol))
    finally: await rest.close()
if __name__=='__main__': asyncio.run(main())
