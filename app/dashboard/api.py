from __future__ import annotations
import asyncio
import time
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .cache import DashboardCache
from .service import DashboardService
from .ws import DashboardHub, heartbeat_all, redis_market_bridge
from app.monitoring import observe_request, metrics_payload, CONTENT_TYPE_LATEST


def create_app(pool=None, redis_url="redis://localhost:6379/0"):
    app=FastAPI(title="Crypto RL Trader Dashboard API", version="7.0.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    cache=DashboardCache(redis_url, ttl=5)
    hub=DashboardHub()
    app.state.pool=pool; app.state.cache=cache; app.state.hub=hub

    @app.get('/api/rate-limit')
    async def rate_limit_pressure():
        from app.monitoring import binance_rate_limit_state
        state=await cache.get("telemetry:binance_rate_limit")
        return state or binance_rate_limit_state()

    def svc():
        if app.state.pool is None: raise HTTPException(503,"database pool not configured")
        return DashboardService(app.state.pool, cache)

    @app.on_event("startup")
    async def startup():
        if app.state.pool is not None:
            app.state.ws_task=asyncio.create_task(heartbeat_all(hub, svc()))
            app.state.market_bridge_task=asyncio.create_task(redis_market_bridge(hub, redis_url))
    @app.on_event("shutdown")
    async def shutdown():
        task=getattr(app.state,"ws_task",None)
        if task: task.cancel()
        bridge=getattr(app.state,"market_bridge_task",None)
        if bridge: bridge.cancel()

    @app.middleware("http")
    async def metrics_middleware(request, call_next):
        started=time.perf_counter()
        try:
            response=await call_next(request)
        except Exception:
            observe_request(request.method,request.url.path,500,time.perf_counter()-started); raise
        observe_request(request.method,request.url.path,response.status_code,time.perf_counter()-started)
        return response

    @app.get("/metrics")
    async def prometheus_metrics():
        from fastapi.responses import Response
        return Response(metrics_payload(),media_type=CONTENT_TYPE_LATEST)

    @app.get("/api/health")
    async def health():
        return {"ok": True, "service":"dashboard", "utc":datetime.now(timezone.utc).isoformat()}

    @app.get("/api/overview")
    async def overview(mode: str="PAPER_TESTNET"): return await svc().overview(mode)

    @app.get("/api/metrics")
    async def metrics(mode: str="PAPER_TESTNET"): return await svc().metrics(mode)

    @app.get("/api/funding")
    async def funding(mode: str="PAPER_TESTNET", symbol: str="BTCUSDT"):
        return await svc().funding(mode, symbol.upper())

    @app.get("/api/timeseries/{source}")
    async def timeseries(source: str, mode: str="PAPER_TESTNET", symbol: str|None=None,
                         start: datetime|None=None, end: datetime|None=None, points: int=2500):
        if start and start.tzinfo is None: start=start.replace(tzinfo=timezone.utc)
        if end and end.tzinfo is None: end=end.replace(tzinfo=timezone.utc)
        if not start: start=datetime.now(timezone.utc)-timedelta(days=1)
        if not end: end=datetime.now(timezone.utc)
        try: return await svc().timeseries(source,mode,symbol,start,end,points)
        except ValueError as e: raise HTTPException(400,str(e))

    @app.get("/api/trades")
    async def trades(mode: str="PAPER_TESTNET", cursor: str|None=None, limit: int=100,
                     symbol: str|None=None, side: str|None=None, status: str|None=None,
                     sort_by: str="update_time", sort_dir: str="desc"):
        return await svc().trades(mode,cursor,limit,symbol,side,status,sort_by,sort_dir)

    @app.get("/api/signals")
    async def signals(mode: str="PAPER_TESTNET", symbol: str="BTCUSDT", start: datetime|None=None, end: datetime|None=None, limit: int=500):
        return {"rows":await svc().signals(mode,symbol,start,end,limit)}

    @app.get("/api/alerts")
    async def alerts(mode: str="PAPER_TESTNET", limit: int=100): return await svc().alerts(mode,limit)

    @app.get("/api/metric-history")
    async def metric_history(mode: str="PAPER_TESTNET", start: datetime|None=None, end: datetime|None=None, limit: int=500):
        return {"rows":await svc().metric_history(mode,start,end,limit)}

    @app.get("/api/diagnostics")
    async def diagnostics(experiment: str|None=None): return await svc().diagnostics(experiment)

    @app.get("/api/benchmarks")
    async def benchmarks(mode: str="PAPER_TESTNET"):
        # Benchmark results are stored/loaded as pre-aggregated snapshots when present.
        async with app.state.pool.acquire() as c:
            exists=await c.fetchval("SELECT to_regclass('dashboard.benchmark_snapshots')")
            if not exists: return {"rows":[]}
            rows=await c.fetch("SELECT benchmark,period_start,period_end,total_return,sharpe,max_drawdown,trade_count FROM dashboard.benchmark_snapshots WHERE mode=$1 ORDER BY period_end DESC LIMIT 100",mode)
        return {"rows":[dict(r) for r in rows]}

    @app.websocket("/ws/live")
    async def live(ws: WebSocket):
        await hub.connect(ws)
        try:
            while True:
                raw=await ws.receive_text()
                try: msg=__import__('json').loads(raw)
                except Exception: continue
                if msg.get('type')=='subscribe':
                    modes=msg.get('modes'); symbols=msg.get('symbols')
                    if modes is None and msg.get('mode') is not None: modes=[msg.get('mode')]
                    if symbols is None and msg.get('symbol') is not None: symbols=[msg.get('symbol')]
                    hub.subscribe(ws,modes,symbols)
                elif msg.get('type')=='resync':
                    mode=str(msg.get('mode','PAPER_TESTNET')).upper()
                    snapshot=await svc().overview(mode)
                    await ws.send_text(__import__('json').dumps({'type':'state_snapshot','channel':'execution_state','mode':mode,'symbol':'','seq':hub.current_sequence('execution_state',mode,''),'data':snapshot},default=str))
                elif msg.get('type')=='market_resync':
                    symbol=str(msg.get('symbol','')).upper()
                    if symbol:
                        import redis.asyncio as redis
                        client=redis.from_url(redis_url,decode_responses=True)
                        try:
                            keys={'book':f'market:book:{symbol}','kline':f'market:kline:{symbol}','trade':f'market:trade:{symbol}','bookTicker':f'market:bookTicker:{symbol}','mark':f'market:mark:{symbol}','ticker':f'market:ticker:{symbol}','liquidation':f'market:liquidation:{symbol}'}
                            state={}
                            for kind,key in keys.items():
                                raw=await client.get(key)
                                if raw:
                                    try: state[kind]=__import__('json').loads(raw)
                                    except Exception: state[kind]=raw
                            await ws.send_text(__import__('json').dumps({'type':'market_snapshot','channel':'market_tick','mode':'MARKET','symbol':symbol,'seq':hub.current_sequence('market_tick','MARKET',symbol),'data':state},default=str))
                        finally: await client.close()
        except WebSocketDisconnect: hub.disconnect(ws)
        except Exception: hub.disconnect(ws)
    return app
