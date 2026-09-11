from __future__ import annotations

import json
import math
from datetime import datetime, timezone, timedelta
from typing import Any

from .lttb import lttb

MAX_POINTS = 2500
MAX_ROWS = 250


class DashboardService:
    def __init__(self, pool, cache):
        self.pool = pool
        self.cache = cache

    async def overview(self, mode: str = "PAPER_TESTNET") -> dict[str, Any]:
        key = f"dash:overview:{mode}"
        cached = await self.cache.get(key)
        if cached:
            return cached
        async with self.pool.acquire() as c:
            latest_order = await c.fetchrow("""
                SELECT symbol, side, status, executed_qty::float8 AS executed_qty,
                       avg_price::float8 AS avg_price, update_time, mode
                FROM execution.orders WHERE mode=$1 ORDER BY update_time DESC LIMIT 1
            """, mode)
            fills = await c.fetchrow("""
                SELECT COALESCE(SUM(CASE WHEN side='BUY' THEN quote_qty ELSE -quote_qty END),0)::float8 AS signed_volume,
                       COUNT(*)::int AS trade_count
                FROM execution.fills WHERE mode=$1 AND trade_time >= date_trunc('day', now())
            """, mode)
            risk = await c.fetchrow("""
                SELECT allowed, reasons, metrics, event_time FROM execution.risk_events
                WHERE mode=$1 ORDER BY event_time DESC LIMIT 1
            """, mode)
            recon = await c.fetchrow("""
                SELECT ok, checked_at, payload FROM execution.reconciliation_events
                WHERE mode=$1 ORDER BY checked_at DESC LIMIT 1
            """, mode)
            latest_user = await c.fetchrow("""
                SELECT event_time,event_type,payload FROM execution.user_events
                WHERE mode=$1 ORDER BY event_time DESC LIMIT 1
            """, mode)
            try:
                ws_health = await c.fetchrow("""
                    SELECT ts,connected,last_event_time,last_error
                    FROM dashboard.ws_health WHERE mode=$1 ORDER BY ts DESC LIMIT 1
                """, mode)
            except Exception:
                # Migration 008 is required for durable heartbeat telemetry, but keep the
                # overview readable while an older database is being migrated.
                ws_health = None
        # Prefer durable account snapshots written by the execution loop. Fall back to
        # ACCOUNT_UPDATE parsing so an older database remains readable after migration.
        account_row = None
        try:
            async with self.pool.acquire() as c:
                account_row = await c.fetchrow("""
                    SELECT ts,wallet_balance,available_balance,equity,unrealized_pnl,
                           total_initial_margin,total_maint_margin,margin_ratio,leverage,today_pnl,positions
                    FROM dashboard.account_snapshots WHERE mode=$1 ORDER BY ts DESC LIMIT 1
                """, mode)
        except Exception:
            # Migration 007 is required for durable account telemetry, but the dashboard
            # remains backward-compatible with databases that have not been migrated yet.
            account_row = None
        account = dict(account_row) if account_row else _extract_account_state(latest_user["payload"] if latest_user else None)
        positions = account.get("positions") or []
        result = {
            "mode": mode,
            "equity": account.get("equity"),
            "wallet_balance": account.get("wallet_balance"),
            "available_balance": account.get("available_balance"),
            "unrealized_pnl": account.get("unrealized_pnl"),
            "today_pnl": account.get("today_pnl"),
            "total_initial_margin": account.get("total_initial_margin"),
            "total_maint_margin": account.get("total_maint_margin"),
            "margin_ratio": account.get("margin_ratio"),
            "leverage": account.get("leverage"),
            "open_positions": positions,
            "connection": {
                "ws": bool(ws_health["connected"]) if ws_health else bool(latest_user),
                "user_stream_connected": bool(ws_health["connected"]) if ws_health else bool(latest_user),
                "last_heartbeat": ws_health["ts"].isoformat() if ws_health else (latest_user["event_time"].isoformat() if latest_user else None),
                "last_event": ws_health["last_event_time"].isoformat() if ws_health and ws_health["last_event_time"] else (latest_user["event_time"].isoformat() if latest_user else None),
                "last_error": ws_health["last_error"] if ws_health else None,
                "reconciliation_ok": bool(recon["ok"]) if recon else None,
            },
            "risk": {"allowed": bool(risk["allowed"]) if risk else True,
                     "reasons": list(risk["reasons"]) if risk else [],
                     "metrics": risk["metrics"] if risk else {}},
            "funding": await self.funding(mode),
            "today_trade_count": fills["trade_count"] if fills else 0,
            "latest_order": _row_json(latest_order),
        }
        await self.cache.set(key, result)
        return result

    async def funding(self, mode: str = "PAPER_TESTNET", symbol: str = "BTCUSDT") -> dict[str, Any]:
        """Return current funding rate, next funding time and countdown.

        Funding is market telemetry, so it is intentionally independent of paper/live mode.
        """
        async with self.pool.acquire() as c:
            row = await c.fetchrow("""
                SELECT event_time,funding_rate,next_funding_time,mark_price,index_price
                FROM market.mark_index_price WHERE symbol=$1 ORDER BY event_time DESC LIMIT 1
            """, symbol)
            hist = await c.fetchrow("""
                SELECT funding_time,funding_rate,mark_price FROM market.funding_rates
                WHERE symbol=$1 ORDER BY funding_time DESC LIMIT 1
            """, symbol)
        if not row and not hist:
            return {"symbol":symbol,"rate":None,"next_funding_time":None,"countdown_seconds":None,"mark_price":None,"index_price":None}
        source = dict(row) if row else {}
        if hist and source.get("funding_rate") is None:
            source["funding_rate"] = hist["funding_rate"]
        nft = source.get("next_funding_time")
        now = datetime.now(timezone.utc)
        countdown = max(0.0, (nft-now).total_seconds()) if nft else None
        return {"symbol":symbol,"rate":float(source["funding_rate"]) if source.get("funding_rate") is not None else None,
                "next_funding_time":nft.astimezone(timezone.utc).isoformat() if nft else None,
                "countdown_seconds":countdown,
                "mark_price":float(source["mark_price"]) if source.get("mark_price") is not None else None,
                "index_price":float(source["index_price"]) if source.get("index_price") is not None else None}

    async def timeseries(self, source: str, mode: str, symbol: str | None,
                         start: datetime | None, end: datetime | None,
                         target_points: int = MAX_POINTS) -> dict[str, Any]:
        target_points = max(10, min(target_points, MAX_POINTS))
        source = source.lower()
        interval = choose_interval(start, end)
        key = f"dash:ts:{source}:{mode}:{symbol}:{start}:{end}:{target_points}:{interval}"
        cached = await self.cache.get(key)
        if cached:
            return cached
        if source in {"equity", "drawdown"}:
            rows = await self._equity(mode, start, end, interval)
            equity_points = [[r["bucket"].timestamp(), float(r["equity"])] for r in rows if r["equity"] is not None]
            if source == "equity":
                points = equity_points
            else:
                high = None; points = []
                for ts, equity in equity_points:
                    high = equity if high is None else max(high, equity)
                    dd = (equity / high - 1.0) if high else 0.0
                    points.append([ts, dd])
        elif source == "price":
            rows = await self._price(symbol or "BTCUSDT", start, end, interval)
            points = [list(r) for r in rows]
        else:
            raise ValueError("source must be equity, drawdown or price")
        sampled = lttb(points, target_points) if len(points) > target_points else points
        result = {"source": source, "interval": interval, "points": sampled, "count": len(sampled)}
        await self.cache.set(key, result)
        return result

    async def _equity(self, mode, start, end, interval):
        # Prefer dashboard hypertable, then compatible execution snapshots.
        params = [mode]
        where = "mode=$1"
        if start:
            params.append(start); where += f" AND ts >= ${len(params)}"
        if end:
            params.append(end); where += f" AND ts <= ${len(params)}"
        table = "dashboard.equity_snapshots"
        bucket_param = len(params) + 1
        query = f"""SELECT time_bucket(${bucket_param}, ts) AS bucket, last(equity, ts)::float8 AS equity
                    FROM {table} WHERE {where} GROUP BY bucket ORDER BY bucket"""
        params.append(interval)
        try:
            async with self.pool.acquire() as c:
                return await c.fetch(query, *params)
        except Exception:
            return []

    async def _price(self, symbol, start, end, interval):
        async with self.pool.acquire() as c:
            view = {"5 minutes":"market.klines_5m", "15 minutes":"market.klines_15m",
                    "1 hour":"market.klines_1h", "1 day":"market.klines_1d"}.get(interval)
            if view:
                params=[symbol]; where="symbol=$1"
                if start: params.append(start); where += f" AND bucket >= ${len(params)}"
                if end: params.append(end); where += f" AND bucket <= ${len(params)}"
                q=f"SELECT bucket, open::float8 open, high::float8 high, low::float8 low, close::float8 close, volume::float8 volume FROM {view} WHERE {where} ORDER BY bucket"
            else:
                params=[symbol,"1m"]; where="symbol=$1 AND interval=$2"
                if start: params.append(start); where += f" AND open_time >= ${len(params)}"
                if end: params.append(end); where += f" AND open_time <= ${len(params)}"
                q=f"SELECT open_time bucket, open::float8 open, high::float8 high, low::float8 low, close::float8 close, volume::float8 volume FROM market.klines WHERE {where} ORDER BY open_time"
            rows=await c.fetch(q,*params)
        return [(r["bucket"].timestamp(),r["open"],r["high"],r["low"],r["close"],r["volume"]) for r in rows]

    async def trades(self, mode: str, cursor: str | None = None, limit: int = 100,
                     symbol: str | None = None, side: str | None = None,
                     status: str | None = None, sort_by: str = "update_time",
                     sort_dir: str = "desc") -> dict[str, Any]:
        limit = max(1, min(limit, MAX_ROWS))
        allowed = {"update_time":"update_time", "executed_qty":"executed_qty", "avg_price":"avg_price", "orig_qty":"orig_qty"}
        field = allowed.get(sort_by, "update_time")
        direction = "ASC" if sort_dir.lower() == "asc" else "DESC"
        args = [mode]; filters = ["mode=$1"]
        if symbol:
            args.append(symbol); filters.append(f"symbol=${len(args)}")
        if side:
            args.append(side.upper()); filters.append(f"side=${len(args)}")
        if status:
            args.append(status.upper()); filters.append(f"status=${len(args)}")
        if cursor:
            import base64, json
            data=json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
            value, oid=data["value"],data["id"]
            if field == "update_time" and isinstance(value,str):
                value=datetime.fromisoformat(value)
            op = ">" if direction == "ASC" else "<"
            args += [value, oid]
            filters.append(f"({field}, exchange_order_id) {op} (${len(args)-1}, ${len(args)})")
        args.append(limit + 1)
        async with self.pool.acquire() as c:
            rows = await c.fetch(f"""
                SELECT symbol,exchange_order_id,client_order_id,side,order_type,status,
                       orig_qty::float8 orig_qty,executed_qty::float8 executed_qty,
                       avg_price::float8 avg_price,update_time,latency_ms
                FROM execution.orders WHERE {' AND '.join(filters)}
                ORDER BY {field} {direction}, exchange_order_id {direction} LIMIT ${len(args)}
            """, *args)
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit-1]
            import base64, json
            value=last[field]
            if hasattr(value,'isoformat'): value=value.isoformat()
            next_cursor=base64.urlsafe_b64encode(json.dumps({"value":value,"id":last["exchange_order_id"]}).encode()).decode()
            rows=rows[:limit]
        return {"rows":[_row_json(r) for r in rows],"next_cursor":next_cursor,"limit":limit,"sort_by":field,"sort_dir":direction.lower()}

    async def signals(self, mode: str, symbol: str, start: datetime | None, end: datetime | None, limit: int=500):
        async with self.pool.acquire() as c:
            rows=await c.fetch("""SELECT ts,symbol,signal,price::float8 price,indicators,model_version
                                  FROM dashboard.signal_events WHERE mode=$1 AND symbol=$2
                                  AND ($3::timestamptz IS NULL OR ts >= $3)
                                  AND ($4::timestamptz IS NULL OR ts <= $4)
                                  ORDER BY ts DESC LIMIT $5""",mode,symbol,start,end,min(limit,MAX_ROWS))
        return [_row_json(r) for r in reversed(rows)]

    async def metrics(self, mode: str = "PAPER_TESTNET") -> dict[str, Any]:
        key=f"dash:metrics:{mode}"; cached=await self.cache.get(key)
        if cached: return cached
        from app.sim.metrics import performance
        async with self.pool.acquire() as c:
            span=await c.fetchrow("SELECT min(ts) min_ts,max(ts) max_ts FROM dashboard.equity_snapshots WHERE mode=$1",mode)
            interval=choose_interval(span["min_ts"],span["max_ts"]) if span and span["min_ts"] and span["max_ts"] else "5 minutes"
            eq_view={"5 minutes":"dashboard.equity_5m","1 hour":"dashboard.equity_1h","1 day":"dashboard.equity_1d"}.get(interval,"dashboard.equity_5m")
            eqrows=await c.fetch(f"SELECT bucket AS ts,equity::float8 AS equity FROM {eq_view} WHERE mode=$1 ORDER BY bucket",mode)
            fills=await c.fetch("SELECT exchange_order_id,trade_time,quote_qty::float8 quote_qty,side FROM execution.fills WHERE mode=$1 ORDER BY trade_time",mode)
            risk=await c.fetchrow("SELECT metrics FROM execution.risk_events WHERE mode=$1 ORDER BY event_time DESC LIMIT 1",mode)
        equity=[float(r['equity']) for r in eqrows if r['equity'] is not None]
        trade_pnl=[]; grouped={}
        for f in fills:
            grouped.setdefault(str(f['exchange_order_id']),[]).append(f)
        for rows in grouped.values():
            pnl=sum((1 if r['side']=='SELL' else -1)*float(r['quote_qty']) for r in rows)
            if pnl: trade_pnl.append(pnl)
        if equity:
            perf=performance(equity,trade_pnl)
            avg_hold=float(sum((r[-1]['trade_time']-r[0]['trade_time']).total_seconds()/60 for r in grouped.values() if len(r)>1)/max(1,sum(1 for r in grouped.values() if len(r)>1)))
        else:
            perf={} ; avg_hold=None
        result={"sharpe":perf.get('Sharpe'),"sortino":perf.get('Sortino'),"calmar":perf.get('Calmar'),"max_drawdown":perf.get('max_drawdown'),
                "win_rate":perf.get('win_rate'),"profit_factor":perf.get('profit_factor'),"expectancy":perf.get('expectancy'),
                "trade_count":len(fills),"average_holding_minutes":avg_hold,"risk":risk['metrics'] if risk else {}}
        await self.cache.set(key,result); return result

    async def alerts(self, mode: str = "PAPER_TESTNET", limit: int = 100):
        async with self.pool.acquire() as c:
            rows = await c.fetch("""
                SELECT event_time,'RISK' kind, array_to_string(reasons, ', ') message, metrics payload
                FROM execution.risk_events WHERE mode=$1
                UNION ALL
                SELECT checked_at,'RECONCILIATION',CASE WHEN ok THEN 'OK' ELSE 'MISMATCH' END,payload
                FROM execution.reconciliation_events WHERE mode=$1
                UNION ALL
                SELECT event_time,event_type,event_type,payload
                FROM execution.user_events WHERE mode=$1
                ORDER BY event_time DESC LIMIT $2
            """, mode, min(limit, MAX_ROWS))
        return [_row_json(r) for r in rows]

    async def trades(self, mode: str, cursor: str | None = None, limit: int = 100,
                     symbol: str | None = None, side: str | None = None,
                     status: str | None = None, sort_by: str = "update_time",
                     sort_dir: str = "desc") -> dict[str, Any]:
        limit = max(1, min(limit, MAX_ROWS))
        allowed = {"update_time":"update_time", "executed_qty":"executed_qty", "avg_price":"avg_price", "orig_qty":"orig_qty"}
        field = allowed.get(sort_by, "update_time")
        direction = "ASC" if sort_dir.lower() == "asc" else "DESC"
        args = [mode]; filters = ["mode=$1"]
        if symbol:
            args.append(symbol); filters.append(f"symbol=${len(args)}")
        if side:
            args.append(side.upper()); filters.append(f"side=${len(args)}")
        if status:
            args.append(status.upper()); filters.append(f"status=${len(args)}")
        if cursor:
            import base64, json
            data=json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
            value, oid=data["value"],data["id"]
            if field == "update_time" and isinstance(value,str): value=datetime.fromisoformat(value)
            op = ">" if direction == "ASC" else "<"
            args += [value, oid]
            filters.append(f"({field}, exchange_order_id) {op} (${len(args)-1}, ${len(args)})")
        args.append(limit + 1)
        async with self.pool.acquire() as c:
            rows = await c.fetch(f"""
                SELECT symbol,exchange_order_id,client_order_id,side,order_type,status,
                       orig_qty::float8 orig_qty,executed_qty::float8 executed_qty,
                       avg_price::float8 avg_price,update_time,latency_ms
                FROM execution.orders WHERE {' AND '.join(filters)}
                ORDER BY {field} {direction}, exchange_order_id {direction} LIMIT ${len(args)}
            """, *args)
        next_cursor = None
        if len(rows) > limit:
            last=rows[limit-1]
            import base64,json
            value=last[field]
            if hasattr(value,'isoformat'): value=value.isoformat()
            next_cursor=base64.urlsafe_b64encode(json.dumps({"value":value,"id":last["exchange_order_id"]}).encode()).decode()
            rows=rows[:limit]
        return {"rows":[_row_json(r) for r in rows],"next_cursor":next_cursor,"limit":limit,"sort_by":field,"sort_dir":direction.lower()}

    async def signals(self, mode: str, symbol: str, start: datetime | None, end: datetime | None, limit: int=500):
        async with self.pool.acquire() as c:
            rows=await c.fetch("""SELECT ts,symbol,signal,price::float8 price,indicators,model_version
                                  FROM dashboard.signal_events WHERE mode=$1 AND symbol=$2
                                  AND ($3::timestamptz IS NULL OR ts >= $3)
                                  AND ($4::timestamptz IS NULL OR ts <= $4)
                                  ORDER BY ts DESC LIMIT $5""",mode,symbol,start,end,min(limit,MAX_ROWS))
        return [_row_json(r) for r in reversed(rows)]

    async def metric_history(self, mode: str = "PAPER_TESTNET", start: datetime | None = None, end: datetime | None = None, limit: int = 500):
        async with self.pool.acquire() as c:
            exists=await c.fetchval("SELECT to_regclass('dashboard.metric_snapshots')")
            if exists:
                rows=await c.fetch("""SELECT ts,sharpe,sortino,calmar,max_drawdown,win_rate,profit_factor,expectancy,trade_count,average_holding_minutes
                                      FROM dashboard.metric_snapshots WHERE mode=$1
                                      AND ($2::timestamptz IS NULL OR ts >= $2) AND ($3::timestamptz IS NULL OR ts <= $3)
                                      ORDER BY ts DESC LIMIT $4""",mode,start,end,min(limit,MAX_ROWS))
                if rows: return [_row_json(r) for r in reversed(rows)]
            eq=await c.fetch("SELECT ts,equity::float8 equity FROM dashboard.equity_snapshots WHERE mode=$1 AND ($2::timestamptz IS NULL OR ts >= $2) AND ($3::timestamptz IS NULL OR ts <= $3) ORDER BY ts",mode,start,end)
        from app.sim.metrics import performance
        rows=[]; window=60
        vals=[(r['ts'],float(r['equity'])) for r in eq if r['equity'] is not None]
        for i,(ts,_) in enumerate(vals):
            sample=vals[max(0,i-window+1):i+1]
            if len(sample)<2: continue
            perf=performance(pd.Series([x[1] for x in sample], index=pd.to_datetime([x[0] for x in sample],utc=True)),[])
            rows.append({"ts":ts,"sharpe":perf.get('Sharpe'),"sortino":perf.get('Sortino'),"calmar":perf.get('Calmar'),"max_drawdown":perf.get('max_drawdown'),"win_rate":None,"profit_factor":None,"expectancy":None,"trade_count":0,"average_holding_minutes":None})
        return rows[-min(limit,MAX_ROWS):]

    async def diagnostics(self, experiment: str | None = None):
        import os
        tracking = os.getenv("MLFLOW_TRACKING_URI")
        if not tracking:
            return {"experiment": experiment, "runs": [], "available": False}
        try:
            import aiohttp
            async with aiohttp.ClientSession() as sess:
                payload={"max_results":20}
                if experiment: payload["filter_string"]=f"attribute.experiment_id = '{experiment}'"
                async with sess.post(tracking.rstrip('/')+"/api/2.0/mlflow/runs/search",json=payload) as r:
                    data=await r.json()
                runs=[]
                for run in data.get("runs",[]):
                    rid=run.get("info",{}).get("run_id")
                    metrics={m["key"]:m["value"] for m in run.get("data",{}).get("metrics",[])}
                    params={p["key"]:p["value"] for p in run.get("data",{}).get("params",[])}
                    history={}
                    for key in ("rollout_ep_rew_mean","reward","policy_gradient_loss","value_loss","entropy_loss"):
                        url=tracking.rstrip('/')+f"/api/2.0/mlflow/metrics/get-history?run_id={rid}&metric_key={key}"
                        async with sess.get(url) as rr:
                            if rr.status==200:
                                h=await rr.json(); history[key]=h.get("metrics",[])
                    runs.append({"run_id":rid,"metrics":metrics,"params":params,"history":history})
            return {"experiment":experiment,"runs":runs,"available":True}
        except Exception as exc:
            return {"experiment":experiment,"runs":[],"available":False,"error":str(exc)}


def choose_interval(start, end):
    if not start or not end: return "1 minute"
    hours = max(1, (end-start).total_seconds()/3600)
    if hours <= 6: return "1 minute"
    if hours <= 48: return "5 minutes"
    if hours <= 14*24: return "15 minutes"
    if hours <= 90*24: return "1 hour"
    return "1 day"


def _row_json(row):
    if row is None: return None
    d = dict(row)
    for k, v in list(d.items()):
        if isinstance(v, datetime): d[k] = v.astimezone(timezone.utc).isoformat()
    return d


def encode_cursor(ts, oid):
    import base64
    raw = f"{ts.astimezone(timezone.utc).isoformat()}|{oid}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(value):
    import base64
    raw = base64.urlsafe_b64decode(value.encode()).decode()
    ts, oid = raw.rsplit('|', 1)
    return datetime.fromisoformat(ts), oid


def _extract_account_state(payload):
    if not payload: return {}
    try: data = json.loads(payload) if isinstance(payload, str) else payload
    except Exception: return {}
    if data.get("e") != "ACCOUNT_UPDATE": return {}
    a = data.get("a", {})
    positions = []
    for p in a.get("P", []):
        qty = float(p.get("pa", 0) or 0)
        if qty:
            mark = float(p.get("mp", 0) or 0)
            liq = float(p.get("li", 0) or 0)
            positions.append({"symbol": p.get("s"), "qty": qty,
                              "entry_price": float(p.get("ep",0) or 0),
                              "mark_price": mark, "liquidation_price": liq,
                              "unrealized_pnl": float(p.get("up",0) or 0),
                              "leverage": float(p.get("l",1) or 1),
                              "margin_type": p.get("mt", "ISOLATED")})
    balances = a.get("B", [])
    usdt = next((b for b in balances if b.get("a") == "USDT"), {})
    wallet = float(usdt.get("wb", 0) or 0)
    cross_wallet = float(usdt.get("cw", wallet) or wallet)
    return {"wallet_balance": wallet, "equity": wallet,
            "available_balance": cross_wallet, "unrealized_pnl": sum(x["unrealized_pnl"] for x in positions),
            "positions": positions, "leverage": max((x["leverage"] for x in positions), default=None),
            "margin_ratio": None, "today_pnl": None}
