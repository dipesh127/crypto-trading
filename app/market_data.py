from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .orderbook import OrderBookReconciler, DepthUpdate
try:
    from .monitoring import observe_market_gap
except Exception:
    observe_market_gap=None

log = logging.getLogger(__name__)


def _dt(ms: int | float | None) -> datetime:
    return datetime.fromtimestamp(float(ms or 0) / 1000.0, tz=timezone.utc)


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


class MarketDataDBWriter:
    def __init__(self, pool):
        self.pool = pool

    async def quality(self, symbol, data_type, flag, *, event_time=None, details=None):
        if observe_market_gap and ("GAP" in str(flag) or "OUT_OF_ORDER" in str(flag) or "CLOCK_SKEW" in str(flag)):
            observe_market_gap(symbol, f"{data_type}:{flag}")
        async with self.pool.acquire() as c:
            await c.execute(
                "INSERT INTO system.data_quality_events(symbol,data_type,event_time,quality_flag,details) VALUES($1,$2,$3,$4,$5::jsonb)",
                symbol, data_type, event_time, flag, _json(details or {}),
            )

    async def server_time(self, server_ms, local_ms, offset_ms):
        async with self.pool.acquire() as c:
            await c.execute(
                "INSERT INTO system.server_time_sync(observed_at,server_time_ms,local_time_ms,offset_ms) VALUES(now(),$1,$2,$3)",
                int(server_ms), int(local_ms), int(offset_ms),
            )

    async def exchange_info(self, info):
        async with self.pool.acquire() as c:
            for s in info.get("symbols", []):
                filters = {x.get("filterType"): x for x in s.get("filters", [])}
                pf, lf, mn = filters.get("PRICE_FILTER", {}), filters.get("LOT_SIZE", filters.get("MARKET_LOT_SIZE", {})), filters.get("MIN_NOTIONAL", {})
                await c.execute("""
                    INSERT INTO market.exchange_info
                    (symbol,status,base_asset,quote_asset,contract_type,price_precision,quantity_precision,
                     tick_size,step_size,min_qty,min_notional,raw,observed_at)
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb,now())
                    ON CONFLICT(symbol) DO UPDATE SET status=EXCLUDED.status,base_asset=EXCLUDED.base_asset,
                    quote_asset=EXCLUDED.quote_asset,contract_type=EXCLUDED.contract_type,
                    price_precision=EXCLUDED.price_precision,quantity_precision=EXCLUDED.quantity_precision,
                    tick_size=EXCLUDED.tick_size,step_size=EXCLUDED.step_size,min_qty=EXCLUDED.min_qty,
                    min_notional=EXCLUDED.min_notional,raw=EXCLUDED.raw,observed_at=now()
                """, s["symbol"], s.get("status", ""), s.get("baseAsset", ""), s.get("quoteAsset", ""),
                    s.get("contractType"), s.get("pricePrecision"), s.get("quantityPrecision"),
                    pf.get("tickSize", 0), lf.get("stepSize", 0), lf.get("minQty", 0), mn.get("notional", mn.get("minNotional", 0)), _json(s))

    async def brackets(self, symbol, data):
        rows = data.get("brackets", []) if isinstance(data, dict) else data
        async with self.pool.acquire() as c:
            for b in rows:
                await c.execute("""
                    INSERT INTO market.leverage_brackets
                    (symbol,bracket,initial_leverage,notional_floor,notional_cap,maint_margin_ratio,cum,notional_coef,observed_at)
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8,now())
                    ON CONFLICT(symbol,bracket) DO UPDATE SET initial_leverage=EXCLUDED.initial_leverage,
                    notional_floor=EXCLUDED.notional_floor,notional_cap=EXCLUDED.notional_cap,
                    maint_margin_ratio=EXCLUDED.maint_margin_ratio,cum=EXCLUDED.cum,
                    notional_coef=EXCLUDED.notional_coef,observed_at=now()
                """, symbol, int(b["bracket"]), int(b["initialLeverage"]), float(b["notionalFloor"]),
                    float(b["notionalCap"]), float(b["maintMarginRatio"]), float(b.get("cum", 0)),
                    float(b["notionalCoef"]) if b.get("notionalCoef") is not None else None)

    async def get_backfill_checkpoint(self, symbol, dataset, interval=''):
        async with self.pool.acquire() as c:
            return await c.fetchrow("SELECT cursor_ms,cursor_id,completed FROM system.backfill_checkpoints WHERE symbol=$1 AND dataset=$2 AND interval=$3",symbol,dataset,interval)

    async def set_backfill_checkpoint(self, symbol, dataset, interval='', *, cursor_ms=None, cursor_id=None, completed=False):
        async with self.pool.acquire() as c:
            await c.execute("""INSERT INTO system.backfill_checkpoints(symbol,dataset,interval,cursor_ms,cursor_id,completed,updated_at) VALUES($1,$2,$3,$4,$5,$6,now())
                ON CONFLICT(symbol,dataset,interval) DO UPDATE SET cursor_ms=EXCLUDED.cursor_ms,cursor_id=EXCLUDED.cursor_id,completed=EXCLUDED.completed,updated_at=now()""",symbol,dataset,interval,cursor_ms,cursor_id,completed)

    async def kline(self, symbol, interval, k, *, source="websocket"):
        vals = (symbol, interval, _dt(k["t"]), _dt(k["T"]), float(k["o"]), float(k["h"]), float(k["l"]),
                float(k["c"]), float(k["v"]), float(k["q"]), int(k["n"]), float(k["V"]), float(k["Q"]),
                int(k.get("f", 0)), int(k.get("L", 0)), _dt(k.get("E")), bool(k.get("x", False)))
        async with self.pool.acquire() as c:
            await c.execute("""
                INSERT INTO market.klines(symbol,interval,open_time,close_time,open,high,low,close,volume,quote_volume,
                trade_count,taker_buy_base_volume,taker_buy_quote_volume,first_trade_id,last_trade_id,event_time,is_closed)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
                ON CONFLICT(symbol,interval,open_time) DO UPDATE SET close_time=EXCLUDED.close_time,open=EXCLUDED.open,
                high=EXCLUDED.high,low=EXCLUDED.low,close=EXCLUDED.close,volume=EXCLUDED.volume,
                quote_volume=EXCLUDED.quote_volume,trade_count=EXCLUDED.trade_count,
                taker_buy_base_volume=EXCLUDED.taker_buy_base_volume,taker_buy_quote_volume=EXCLUDED.taker_buy_quote_volume,
                first_trade_id=EXCLUDED.first_trade_id,last_trade_id=EXCLUDED.last_trade_id,event_time=EXCLUDED.event_time,
                is_closed=EXCLUDED.is_closed
            """, *vals)

    async def trade(self, symbol, d, *, source="websocket"):
        async with self.pool.acquire() as c:
            await c.execute("""
                INSERT INTO market.trades_raw(symbol,event_time,trade_time,agg_id,price,quantity,first_trade_id,last_trade_id,buyer_is_maker,source)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT(symbol,agg_id) DO NOTHING
            """, symbol, _dt(d.get("E")), _dt(d.get("T", d.get("E"))), int(d["a"]), float(d["p"]), float(d["q"]),
                int(d.get("f", 0)), int(d.get("l", 0)), bool(d.get("m", False)), source)

    async def ticker_24h(self, d):
        symbol=d["s"].upper()
        async with self.pool.acquire() as c:
            await c.execute("""
                INSERT INTO market.ticker_24h(symbol,event_time,transaction_time,update_id,price_change,price_change_percent,weighted_avg_price,last_price,last_qty,open_price,high_price,low_price,volume,quote_volume,open_time,close_time,first_trade_id,last_trade_id,trade_count,raw)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20::jsonb)
                ON CONFLICT(symbol,update_id) DO UPDATE SET last_price=EXCLUDED.last_price,volume=EXCLUDED.volume,quote_volume=EXCLUDED.quote_volume,raw=EXCLUDED.raw,event_time=EXCLUDED.event_time
            """, symbol, _dt(d.get("E")), _dt(d.get("E")), int(d.get("u",d.get("U",d.get("E",0)))),
                float(d.get("p",0)),float(d.get("P",0)),float(d.get("w",0)),float(d.get("c",0)),float(d.get("Q",0)),float(d.get("o",0)),float(d.get("h",0)),float(d.get("l",0)),float(d.get("v",0)),float(d.get("q",0)),_dt(d.get("O")),_dt(d.get("C")),int(d.get("F",0)),int(d.get("L",0)),int(d.get("n",0)),_json(d))

    async def book_ticker(self, d):
        symbol = d["s"].upper()
        async with self.pool.acquire() as c:
            await c.execute("""
                INSERT INTO market.book_ticker(symbol,event_time,transaction_time,update_id,bid_price,bid_qty,ask_price,ask_qty)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT(symbol,update_id) DO NOTHING
            """, symbol, _dt(d.get("E")), _dt(d.get("T")), int(d["u"]), float(d["b"]), float(d["B"]), float(d["a"]), float(d["A"]))

    async def mark(self, d):
        async with self.pool.acquire() as c:
            await c.execute("""
                INSERT INTO market.mark_index_price(symbol,event_time,transaction_time,mark_price,index_price,estimated_settle_price,funding_rate,next_funding_time)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT(symbol,event_time) DO UPDATE SET
                mark_price=EXCLUDED.mark_price,index_price=EXCLUDED.index_price,estimated_settle_price=EXCLUDED.estimated_settle_price,
                funding_rate=EXCLUDED.funding_rate,next_funding_time=EXCLUDED.next_funding_time
            """, d["s"].upper(), _dt(d.get("E")), _dt(d.get("E")), float(d["p"]), float(d["i"]),
                float(d["P"]) if d.get("P") else None, float(d["r"]) if d.get("r") is not None else None, _dt(d.get("T")))

    async def funding(self, symbol, rows, *, source="rest"):
        async with self.pool.acquire() as c:
            for d in rows:
                await c.execute("""
                    INSERT INTO market.funding_rates(symbol,funding_time,funding_rate,mark_price)
                    VALUES($1,$2,$3,$4) ON CONFLICT(symbol,funding_time) DO UPDATE SET funding_rate=EXCLUDED.funding_rate,mark_price=EXCLUDED.mark_price
                """, symbol, _dt(d["fundingTime"]), float(d["fundingRate"]), float(d["markPrice"]) if d.get("markPrice") else None)

    async def open_interest(self, symbol, d, *, source="rest"):
        # /futures/data/openInterestHist uses timestamp, sumOpenInterest and sumOpenInterestValue.
        ts = d.get("timestamp", d.get("time", int(time.time() * 1000)))
        oi = d.get("sumOpenInterest", d.get("openInterest", 0))
        value = d.get("sumOpenInterestValue", d.get("oiValue"))
        async with self.pool.acquire() as c:
            await c.execute("""
                INSERT INTO market.open_interest(symbol,event_time,open_interest,open_interest_value,source)
                VALUES($1,$2,$3,$4,$5) ON CONFLICT(symbol,event_time,source) DO UPDATE SET open_interest=EXCLUDED.open_interest,open_interest_value=EXCLUDED.open_interest_value
            """, symbol, _dt(ts), float(oi), float(value) if value is not None else None, source)

    async def top_ratio(self, symbol, d, *, source="rest"):
        ts = d.get("timestamp", d.get("time", int(time.time() * 1000)))
        async with self.pool.acquire() as c:
            await c.execute("""
                INSERT INTO market.top_trader_ratios(symbol,event_time,period,long_short_ratio,long_account,short_account,source)
                VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT(symbol,event_time,period,source) DO UPDATE SET
                long_short_ratio=EXCLUDED.long_short_ratio,long_account=EXCLUDED.long_account,short_account=EXCLUDED.short_account
            """, symbol, _dt(ts), d.get("period", "5m"), float(d.get("longShortRatio", 0)), float(d.get("longAccount", 0)), float(d.get("shortAccount", 0)), source)

    async def liquidation(self, d, *, source="websocket"):
        o = d.get("o", d)
        async with self.pool.acquire() as c:
            await c.execute("""
                INSERT INTO market.liquidations(symbol,event_time,transaction_time,side,order_type,time_in_force,original_quantity,price,
                average_price,last_filled_quantity,filled_accumulated_quantity,status,execution_type,source)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                ON CONFLICT(symbol,event_time,transaction_time,side,execution_type) DO UPDATE SET
                original_quantity=EXCLUDED.original_quantity,price=EXCLUDED.price,average_price=EXCLUDED.average_price,
                last_filled_quantity=EXCLUDED.last_filled_quantity,filled_accumulated_quantity=EXCLUDED.filled_accumulated_quantity,status=EXCLUDED.status
            """, o["s"].upper(), _dt(d.get("E")), _dt(o.get("T", d.get("E"))), o.get("S", ""), o.get("o"), o.get("f"),
                float(o.get("q", 0)), float(o.get("p", 0)), float(o.get("ap", 0)), float(o.get("l", 0)), float(o.get("z", 0)),
                o.get("X"), o.get("x"), source)

    async def orderbook_snapshot(self, symbol, snapshot, *, source="rest_snapshot"):
        async with self.pool.acquire() as c:
            await c.execute("""
                INSERT INTO market.orderbook_snapshots(symbol,event_time,snapshot_time,last_update_id,bids,asks,depth_limit,checksum_ok,source)
                VALUES($1,now(),now(),$2,$3::jsonb,$4::jsonb,$5,$6,$7)
            """, symbol, int(snapshot["lastUpdateId"]), _json(snapshot.get("bids", [])), _json(snapshot.get("asks", [])),
                len(snapshot.get("bids", [])), True, source)

    async def orderbook_update(self, d, *, applied=False, quality_flag="OK"):
        async with self.pool.acquire() as c:
            await c.execute("""
                INSERT INTO market.orderbook_updates(symbol,event_time,first_update_id,final_update_id,prev_final_update_id,bids,asks,applied,quality_flag)
                VALUES($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8,$9)
                ON CONFLICT(symbol,event_time,first_update_id,final_update_id) DO UPDATE SET applied=EXCLUDED.applied,quality_flag=EXCLUDED.quality_flag
            """, d.symbol, _dt(d.event_time_ms), d.first_update_id, d.final_update_id, d.prev_final_update_id,
                _json(d.bids), _json(d.asks), applied, quality_flag)


class RedisMarketState:
    def __init__(self, redis):
        self.redis = redis

    async def set_json(self, key, value):
        await self.redis.set(key, _json(value))

    async def publish(self, stream, payload):
        await self.redis.xadd(stream, {"data": _json(payload)}, maxlen=100_000, approximate=True)

    async def book(self, symbol, book):
        await self.set_json(f"market:book:{symbol}", book)

    async def tick(self, kind, symbol, payload):
        await self.set_json(f"market:{kind}:{symbol}", payload)
        await self.publish(f"market:{kind}", payload)


class PriceGuard:
    def __init__(self, window=300, z_threshold=12.0):
        self.window=window; self.z_threshold=z_threshold; self.prices=defaultdict(lambda: deque(maxlen=window))

    def accept(self, key, price):
        price=float(price)
        if not math.isfinite(price) or price <= 0: return False, "invalid_price"
        h=self.prices[key]
        if len(h) >= 30:
            s=pd.Series(h, dtype=float); med=float(s.median()); mad=float((s-med).abs().median())
            if mad > 0 and abs(price-med)/(1.4826*mad) > self.z_threshold:
                return False, "fat_finger_price"
        h.append(price)
        return True, "OK"


class MarketDataIngestion:
    """Binance USDT-M market-data ingestion: WS + REST backfill + DB + Redis Streams."""
    def __init__(self, settings, rest, pool, redis):
        self.s=settings; self.rest=rest; self.db=MarketDataDBWriter(pool); self.redis=RedisMarketState(redis)
        self.books={sym:OrderBookReconciler(sym,settings.orderbook_buffer_max) for sym in settings.symbol_list}
        self.guard=PriceGuard(); self.last_kline_open={}; self.last_event_ms={}; self.stop=asyncio.Event(); self.ws_task=None; self.poll_tasks=[]

    async def bootstrap(self):
        await self.rest.sync_server_time()
        now=int(time.time()*1000)
        await self.db.server_time(now + self.rest.offset_ms, now, self.rest.offset_ms)
        info=await self.rest.exchange_info(); available={x["symbol"] for x in info.get("symbols", [])}
        missing=set(self.s.symbol_list)-available
        if missing: raise RuntimeError(f"symbols missing from exchangeInfo: {sorted(missing)}")
        await self.db.exchange_info(info)
        for sym in self.s.symbol_list:
            try:
                await self.db.brackets(sym, await self.rest.leverage_bracket(sym))
            except Exception as exc:
                await self.db.quality(sym,"exchange_info","LEVERAGE_BRACKET_ERROR",details={"error":str(exc)})
                raise
        # Historical bootstrap gives downstream features enough data immediately and closes gaps at startup.
        await asyncio.gather(*(self.backfill_symbol(sym, days=self.s.historical_backfill_days, batch_limit=self.s.backfill_batch_limit) for sym in self.s.symbol_list))
        # Order books are snapshotted only after the websocket has started so no U/u updates are lost.

    async def _snapshot(self, sym):
        snap=await self.rest.depth(sym,self.s.orderbook_depth_limit)
        self.books[sym].initialize_from_snapshot(snap)
        await self.db.orderbook_snapshot(sym,snap)
        if not self.books[sym].ready:
            await self.db.quality(sym,"orderbook","RESYNC_REQUIRED",details={"lastUpdateId":snap.get("lastUpdateId")})
        else:
            await self._cache_book(sym)

    async def backfill_symbol(self, sym, bars=1000, days=None, batch_limit=1000):
        interval_steps={"1m":60000,"3m":180000,"5m":300000,"15m":900000,"1h":3600000,"4h":14400000,"1d":86400000}
        for interval in self.s.interval_list:
            step_ms=interval_steps[interval]
            if days is None:
                rows=await self.rest.klines(sym,interval,limit=bars)
                prev=None
                for r in rows:
                    k={"t":r[0],"T":r[6],"o":r[1],"h":r[2],"l":r[3],"c":r[4],"v":r[5],"q":r[7],"n":r[8],"V":r[9],"Q":r[10],"f":r[11],"L":r[12],"E":r[6],"x":True}
                    await self.db.kline(sym,interval,k,source="rest_backfill")
                    prev=int(k["t"])
                continue
            end=int(time.time()*1000); start=end-int(days)*86400000
            ck=await self.db.get_backfill_checkpoint(sym,'klines',interval)
            resume=int(ck['cursor_ms'])+step_ms if ck and ck['cursor_ms'] else start
            cursor=max(start,resume); page_limit=min(int(batch_limit),1000); prev=None
            while cursor<end:
                rows=await self.rest.klines(sym,interval,startTime=cursor,endTime=end,limit=page_limit)
                if not rows: break
                for r in rows:
                    k={"t":r[0],"T":r[6],"o":r[1],"h":r[2],"l":r[3],"c":r[4],"v":r[5],"q":r[7],"n":r[8],"V":r[9],"Q":r[10],"f":r[11],"L":r[12],"E":r[6],"x":True}
                    if prev is not None and int(k["t"])-int(prev) != step_ms:
                        await self.db.quality(sym,"kline","GAP_DETECTED",event_time=_dt(k["t"]),details={"interval":interval,"previous_open_ms":prev,"current_open_ms":k["t"]})
                    await self.db.kline(sym,interval,k,source="rest_backfill"); prev=int(k["t"])
                await self.db.set_backfill_checkpoint(sym,'klines',interval,cursor_ms=prev,completed=False)
                last=int(rows[-1][0]); nxt=last+step_ms
                if nxt<=cursor: break
                cursor=nxt
                if len(rows)<page_limit: break
            if prev is not None: await self.db.set_backfill_checkpoint(sym,'klines',interval,cursor_ms=prev,completed=True)

        trade_end=int(time.time()*1000); trade_start=trade_end-int(days)*86400000 if days is not None else None
        ck=await self.db.get_backfill_checkpoint(sym,'aggTrades','')
        if ck and ck['completed'] and (trade_start is None or not ck['cursor_ms'] or int(ck['cursor_ms'])>=trade_end-1000):
            pass
        else:
            cursor_id=int(ck['cursor_id']) if ck and ck['cursor_id'] else None
            while True:
                kw={"limit":min(int(batch_limit),1000)}
                if cursor_id is not None: kw["fromId"]=cursor_id
                elif trade_start is not None: kw["startTime"]=trade_start; kw["endTime"]=trade_end
                batch=await self.rest.agg_trades(sym,**kw)
                if not batch: break
                for td in batch:
                    tms=int(td.get("T",td.get("E",0)))
                    if trade_start is not None and not (trade_start<=tms<=trade_end): continue
                    await self.db.trade(sym,{**td,"E":tms},source="rest_backfill")
                last_id=max(int(x["a"]) for x in batch); last_ms=max(int(x.get("T",x.get("E",0))) for x in batch)
                await self.db.set_backfill_checkpoint(sym,'aggTrades','',cursor_ms=last_ms,cursor_id=last_id,completed=False)
                if len(batch)<kw["limit"] or last_ms>=trade_end or not batch: break
                cursor_id=last_id+1
            await self.db.set_backfill_checkpoint(sym,'aggTrades','',cursor_ms=trade_end,cursor_id=cursor_id,completed=True)

        if days is None:
            funding=await self.rest.funding(sym,limit=1000); await self.db.funding(sym,funding)
            for d in await self.rest.open_interest_hist(sym,period="5m",limit=500): await self.db.open_interest(sym,d,source="rest_history")
            for d in await self.rest.top_long_short(sym,period="5m",limit=500): await self.db.top_ratio(sym,d,source="rest_history")
            for d in await self.rest.top_position_ratio(sym,period="5m",limit=500): await self.db.top_ratio(sym,{**d,"period":"5m_position"},source="rest_position_ratio")
        else:
            end_ms=int(time.time()*1000); start_ms=end_ms-int(days)*86400000
            async def paginate(fetch, limit, step_ms=300000):
                cursor=start_ms; seen=set()
                while cursor<end_ms:
                    batch=await fetch(cursor,end_ms,limit)
                    if not batch: break
                    for item in batch: yield item
                    stamp_key='fundingTime' if 'fundingTime' in batch[0] else ('timestamp' if 'timestamp' in batch[0] else 'time')
                    last=max(int(x.get(stamp_key,0)) for x in batch); nxt=last+step_ms
                    if nxt<=cursor or last in seen: break
                    seen.add(last); cursor=nxt
                    if len(batch)<limit: break
            async def funding_fetch(a,b,l): return await self.rest.request('GET','/fapi/v1/fundingRate',{'symbol':sym,'startTime':a,'endTime':b,'limit':l})
            async def oi_fetch(a,b,l): return await self.rest.request('GET','/futures/data/openInterestHist',{'symbol':sym,'period':'5m','startTime':a,'endTime':b,'limit':l})
            async def ratio_fetch(a,b,l): return await self.rest.request('GET','/futures/data/topLongShortAccountRatio',{'symbol':sym,'period':'5m','startTime':a,'endTime':b,'limit':l})
            async def position_fetch(a,b,l): return await self.rest.request('GET','/futures/data/topLongShortPositionRatio',{'symbol':sym,'period':'5m','startTime':a,'endTime':b,'limit':l})
            async for d in paginate(funding_fetch,1000): await self.db.funding(sym,[d])
            async for d in paginate(oi_fetch,500): await self.db.open_interest(sym,d,source="rest_history")
            async for d in paginate(ratio_fetch,500): await self.db.top_ratio(sym,d,source="rest_history")
            async for d in paginate(position_fetch,500): await self.db.top_ratio(sym,{**d,"period":"5m_position"},source="rest_position_ratio")
        try: await self.db.open_interest(sym,await self.rest.open_interest(sym),source="rest_current")
        except Exception as exc: await self.db.quality(sym,"open_interest","REST_ERROR",details={"error":str(exc)})
        try:
            ticker=await self.rest.ticker_24h(sym); await self.redis.tick("ticker",sym,ticker)
        except Exception as exc: await self.db.quality(sym,"ticker","REST_ERROR",details={"error":str(exc)})

    async def start(self):
        self.stop.clear()
        streams=[]
        for sym in self.s.symbol_list:
            x=sym.lower()
            streams.extend([f"{x}@aggTrade",f"{x}@depth@100ms",f"{x}@bookTicker",f"{x}@markPrice@1s",f"{x}@forceOrder",f"{x}@ticker"])
            streams.extend(f"{x}@kline_{tf}" for tf in self.s.interval_list)
        from .ws import CombinedStreams
        async def handler(d): await self.handle(d)
        self.ws_task=asyncio.create_task(CombinedStreams(self.s.binance_ws_base_url,streams,handler).run(),name="market-ws")
        self.poll_tasks=[asyncio.create_task(self._poll_market(sym),name=f"market-poll-{sym}") for sym in self.s.symbol_list]
        # Re-run snapshots after WS is live so U/u bridging is performed correctly.
        await asyncio.sleep(0.25)
        for sym in self.s.symbol_list:
            if not self.books[sym].ready:
                await self._snapshot(sym)

    async def stop_service(self):
        self.stop.set()
        if self.ws_task: self.ws_task.cancel()
        for t in self.poll_tasks: t.cancel()
        for t in [self.ws_task,*self.poll_tasks]:
            if t:
                try: await t
                except asyncio.CancelledError: pass

    async def _poll_market(self,sym):
        while not self.stop.is_set():
            try:
                await asyncio.sleep(300)
                oi=await self.rest.open_interest(sym); await self.db.open_interest(sym,oi,source="rest_current"); await self.redis.tick("open_interest",sym,oi)
                for d in await self.rest.open_interest_hist(sym,period="5m",limit=2): await self.db.open_interest(sym,d,source="rest_history")
                for d in await self.rest.top_long_short(sym,period="5m",limit=2): await self.db.top_ratio(sym,d,source="rest_history")
                for d in await self.rest.top_position_ratio(sym,period="5m",limit=2): await self.db.top_ratio(sym,{**d,"period":"5m_position"},source="rest_position_ratio")
                for d in await self.rest.funding(sym,limit=2): await self.db.funding(sym,[d])
            except asyncio.CancelledError: raise
            except Exception as exc:
                log.exception("market poll failed for %s",sym)
                await self.db.quality(sym,"rest_poll","REST_ERROR",details={"error":str(exc)})

    async def _cache_book(self,sym):
        b=self.books[sym].book
        if not b: return
        bids=sorted(((str(p),str(q)) for p,q in b.bids.items()),key=lambda x:float(x[0]),reverse=True)[:20]
        asks=sorted(((str(p),str(q)) for p,q in b.asks.items()),key=lambda x:float(x[0]))[:20]
        await self.redis.book(sym,{"symbol":sym,"lastUpdateId":b.last_update_id,"bids":bids,"asks":asks,"ts":datetime.now(timezone.utc).isoformat()})

    async def handle(self,d):
        e=d.get("e")
        sym=d.get("s","").upper()
        if not sym: return
        event_ms=int(d.get("E",0) or 0)
        if event_ms:
            now_ms=int(time.time()*1000)
            try:
                from .monitoring import observe_market_event_age
                observe_market_event_age(sym, e or "unknown", (now_ms-event_ms)/1000.0)
            except Exception: pass
            if abs(now_ms-event_ms) > int(getattr(self.s,"max_clock_skew_ms",1000)):
                await self.db.quality(sym,e or "unknown","CLOCK_SKEW",event_time=_dt(event_ms),details={"event_ms":event_ms,"local_ms":now_ms,"skew_ms":now_ms-event_ms})
            last=self.last_event_ms.get((sym,e))
            if last is not None and event_ms < last:
                await self.db.quality(sym,e or "unknown","OUT_OF_ORDER",event_time=_dt(event_ms),details={"previous_event_ms":last,"current_event_ms":event_ms})
            self.last_event_ms[(sym,e)]=max(event_ms,last or 0)
        if e=="kline":
            k=d.get("k",{}); price=k.get("c")
            ok,flag=self.guard.accept(f"{sym}:kline",price)
            if not ok:
                await self.db.quality(sym,"kline",flag,event_time=_dt(d.get("E")),details={"price":price}); return
            interval=k.get("i")
            if bool(k.get("x")):
                step_ms={"1m":60000,"3m":180000,"5m":300000,"15m":900000,"1h":3600000,"4h":14400000,"1d":86400000}.get(interval)
                prev=self.last_kline_open.get((sym,interval))
                if prev is not None and step_ms and int(k["t"])-prev != step_ms:
                    await self.db.quality(sym,"kline","GAP_DETECTED",event_time=_dt(k["t"]),details={"interval":interval,"previous_open_ms":prev,"current_open_ms":k["t"]})
                    missing_start=prev+step_ms; missing_end=int(k["t"])-step_ms
                    if missing_start<=missing_end:
                        for r in await self.rest.klines(sym,interval,startTime=missing_start,endTime=missing_end,limit=1000):
                            kk={"t":r[0],"T":r[6],"o":r[1],"h":r[2],"l":r[3],"c":r[4],"v":r[5],"q":r[7],"n":r[8],"V":r[9],"Q":r[10],"f":r[11],"L":r[12],"E":r[6],"x":True}
                            await self.db.kline(sym,interval,kk,source="rest_gap_backfill")
                self.last_kline_open[(sym,interval)]=int(k["t"])
            await self.db.kline(sym,interval,k)
            await self.redis.tick("kline",sym,{"symbol":sym,"event":"kline","interval":k.get("i"),"open_time":k.get("t"),"close_time":k.get("T"),"open":k.get("o"),"high":k.get("h"),"low":k.get("l"),"close":k.get("c"),"volume":k.get("v"),"quote_volume":k.get("q"),"trade_count":k.get("n"),"taker_buy_base_volume":k.get("V"),"taker_buy_quote_volume":k.get("Q"),"closed":k.get("x"),"first_trade_id":k.get("f"),"last_trade_id":k.get("L"),"event_time":k.get("E")})
        elif e=="aggTrade":
            ok,flag=self.guard.accept(f"{sym}:trade",d.get("p"))
            if not ok: await self.db.quality(sym,"aggTrade",flag,event_time=_dt(d.get("E")),details={"price":d.get("p")}); return
            await self.db.trade(sym,d); await self.redis.tick("trade",sym,d)
        elif e=="depthUpdate":
            u=DepthUpdate(sym,int(d.get("E",0)),int(d["U"]),int(d["u"]),int(d.get("pu")) if d.get("pu") is not None else None,
                          tuple((str(x[0]),str(x[1])) for x in d.get("b",[])),tuple((str(x[0]),str(x[1])) for x in d.get("a",[])))
            book=self.books[sym]; await self.db.orderbook_update(u,applied=False)
            before=book.ready; book.apply_live(u); applied=book.ready and (not before or not book.resync_required)
            if book.resync_required:
                await self.db.quality(sym,"orderbook","GAP_DETECTED",event_time=_dt(u.event_time_ms),details={"U":u.first_update_id,"u":u.final_update_id,"last":book.book.last_update_id if book.book else None})
                # Immediate REST snapshot restores the stream after a gap; the current update is buffered.
                await self._snapshot(sym)
            else:
                await self.db.orderbook_update(u,applied=applied)
                if book.ready: await self._cache_book(sym)
        elif e=="24hrTicker" or e=="ticker":
            await self.db.ticker_24h(d); await self.redis.tick("ticker",sym,d)
        elif e=="bookTicker":
            ok,flag=self.guard.accept(f"{sym}:book",d.get("b"))
            if not ok: await self.db.quality(sym,"bookTicker",flag,event_time=_dt(d.get("E")),details={"bid":d.get("b")}); return
            await self.db.book_ticker(d); await self.redis.tick("bookTicker",sym,d)
        elif e=="markPriceUpdate":
            await self.db.mark(d); await self.redis.tick("mark",sym,d)
        elif e=="forceOrder":
            await self.db.liquidation(d); await self.redis.tick("liquidation",sym,d)
