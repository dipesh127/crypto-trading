import hashlib,hmac,time,asyncio,json
from urllib.parse import urlencode
import aiohttp
from .rate_limit import BinanceLimiter

class BinanceREST:
    def __init__(self,base_url,api_key="",api_secret="",recv_window_ms=5000,ws_base_url=None,*,raw_requests_per_minute=1200,order_requests_per_minute=1200,weight_per_minute=2400,state_store=None,state_key="telemetry:binance_rate_limit"):
        self.base_url=base_url.rstrip("/"); self.api_key=api_key; self.api_secret=api_secret
        self.ws_base_url=(ws_base_url or "wss://stream.binancefuture.com").rstrip("/")
        self.recv_window_ms=recv_window_ms; self.offset_ms=0; self.session=None
        self.limiter=BinanceLimiter(weight_per_minute=weight_per_minute,order_requests_per_minute=order_requests_per_minute,raw_requests_per_minute=raw_requests_per_minute)
        self.state_store=state_store; self.state_key=state_key
        self._error_callback=None

    def set_error_callback(self, callback):
        """Register a sync/async callback invoked for every failed REST attempt."""
        self._error_callback=callback

    async def _report_error(self, exc, *, method, path):
        if self._error_callback is None: return
        try:
            result=self._error_callback(exc, method=method, path=path)
            if asyncio.iscoroutine(result): await result
        except Exception:
            import logging; logging.getLogger(__name__).exception("REST error callback failed")
    async def start(self): self.session=aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
    async def close(self):
        if self.session: await self.session.close()

    async def _persist_rate_limit_state(self):
        """Expose the latest shared limiter state to all dashboard processes."""
        if self.state_store is None:
            return
        try:
            from app.monitoring import binance_rate_limit_state
            state=binance_rate_limit_state()
            state.update({"weight_remaining": max(0.0, self.limiter.weight.tokens),
                          "orders_remaining": max(0.0, self.limiter.orders.tokens),
                          "raw_remaining": max(0.0, self.limiter.raw_requests.tokens),
                          "updated_at": time.time()})
            await self.state_store.set(self.state_key, json.dumps(state), ex=7 * 24 * 60 * 60)
        except Exception:
            # Metrics must never make a market-data or trading request fail.
            pass
    def _headers(self): return {"X-MBX-APIKEY":self.api_key} if self.api_key else {}
    def _signed(self,p):
        p=dict(p); p["timestamp"]=int(time.time()*1000)+self.offset_ms; p["recvWindow"]=self.recv_window_ms
        q=urlencode(p); p["signature"]=hmac.new(self.api_secret.encode(),q.encode(),hashlib.sha256).hexdigest()
        return p
    async def request(self,method,path,params=None,signed=False,weight=1,order_count=0):
        last=None
        for attempt in range(4):
            await self.limiter.acquire(weight, order_count)
            await self._persist_rate_limit_state()
            p=self._signed(params or {}) if signed else dict(params or {})
            try:
                async with self.session.request(method,self.base_url+path,params=p,headers=self._headers()) as r:
                    # Binance exposes live minute usage; feed it back into the client limiter.
                    self.limiter.observe_headers(r.headers)
                    if r.status>=400:
                        try:
                            from app.monitoring import observe_binance_http_status
                            observe_binance_http_status(r.status)
                        except Exception: pass
                        body=await r.text()
                        exc=RuntimeError(f"Binance HTTP {r.status}: {body}")
                        await self._report_error(exc,method=method,path=path)
                        try:
                            from app.monitoring import observe_rest_error
                            observe_rest_error("UNKNOWN",path)
                        except Exception: pass
                        last=exc
                        if r.status in (418,429):
                            retry_after=float(r.headers.get("Retry-After","1"))
                            await asyncio.sleep(max(retry_after, min(2**attempt, 8)))
                        else:
                            await asyncio.sleep(min(0.25*(2**attempt),4))
                        await self._persist_rate_limit_state()
                        continue
                    result=await r.json()
                    # Header feedback is asynchronous; yield once before snapshotting it.
                    await asyncio.sleep(0)
                    await self._persist_rate_limit_state()
                    return result
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._report_error(exc,method=method,path=path)
                try:
                    from app.monitoring import observe_rest_error
                    observe_rest_error("UNKNOWN",path)
                except Exception: pass
                last=exc
                await asyncio.sleep(min(0.25*(2**attempt),4))
        raise last or RuntimeError("Binance request failed")

    async def sync_server_time(self):
        local=int(time.time()*1000); data=await self.request("GET","/fapi/v1/time")
        self.offset_ms=int(data["serverTime"])-local; return self.offset_ms
    async def exchange_info(self): return await self.request("GET","/fapi/v1/exchangeInfo")
    async def depth(self,symbol,limit=1000): return await self.request("GET","/fapi/v1/depth",{"symbol":symbol,"limit":limit},weight=20)
    async def klines(self,symbol,interval,**kw): return await self.request("GET","/fapi/v1/klines",{"symbol":symbol,"interval":interval,**kw})
    async def funding(self,symbol,limit=1000): return await self.request("GET","/fapi/v1/fundingRate",{"symbol":symbol,"limit":limit})
    async def ticker_24h(self,symbol): return await self.request("GET","/fapi/v1/ticker/24hr",{"symbol":symbol})
    async def agg_trades(self,symbol,**kw): return await self.request("GET","/fapi/v1/aggTrades",{"symbol":symbol,**kw},weight=20)
    async def open_interest(self,symbol): return await self.request("GET","/fapi/v1/openInterest",{"symbol":symbol})
    async def open_interest_hist(self,symbol,period="5m",limit=500):
        return await self.request("GET","/futures/data/openInterestHist",{"symbol":symbol,"period":period,"limit":limit})
    async def top_long_short(self,symbol,period="5m",limit=500):
        return await self.request("GET","/futures/data/topLongShortAccountRatio",{"symbol":symbol,"period":period,"limit":limit})
    async def top_position_ratio(self,symbol,period="5m",limit=500):
        return await self.request("GET","/futures/data/topLongShortPositionRatio",{"symbol":symbol,"period":period,"limit":limit})
    async def leverage_bracket(self,symbol):
        return await self.request("GET","/fapi/v1/leverageBracket",{"symbol":symbol},signed=True)
    async def new_order(self, **params):
        return await self.request("POST", "/fapi/v1/order", params, signed=True, weight=1, order_count=1)

    async def cancel_order(self, symbol, order_id=None, orig_client_order_id=None):
        params={"symbol":symbol}
        if order_id is not None: params["orderId"]=order_id
        if orig_client_order_id is not None: params["origClientOrderId"]=orig_client_order_id
        return await self.request("DELETE", "/fapi/v1/order", params, signed=True, weight=1, order_count=1)

    async def open_orders(self, symbol=None):
        return await self.request("GET", "/fapi/v1/openOrders", ({"symbol":symbol} if symbol else {}), signed=True, weight=1)

    async def user_trades(self,symbol,**kw): return await self.request("GET","/fapi/v1/userTrades",{"symbol":symbol,**kw},signed=True,weight=5)
    async def order_status(self, symbol, order_id=None, orig_client_order_id=None):
        params={"symbol":symbol}
        if order_id is not None: params["orderId"]=order_id
        if orig_client_order_id is not None: params["origClientOrderId"]=orig_client_order_id
        return await self.request("GET", "/fapi/v1/order", params, signed=True, weight=1)

    async def position_risk(self, symbol=None):
        return await self.request("GET", "/fapi/v3/positionRisk", ({"symbol":symbol} if symbol else {}), signed=True, weight=5)

    async def account(self):
        return await self.request("GET", "/fapi/v2/account", signed=True, weight=5)

    async def create_listen_key(self):
        data=await self.request("POST", "/fapi/v1/listenKey", {}, signed=False, weight=1)
        return data["listenKey"]

    async def keepalive_listen_key(self, listen_key):
        data=await self.request("PUT", "/fapi/v1/listenKey", {"listenKey":listen_key}, signed=False, weight=1)
        return data.get("listenKey", listen_key)

    async def close_listen_key(self, listen_key):
        return await self.request("DELETE", "/fapi/v1/listenKey", {"listenKey":listen_key}, signed=False, weight=1)

    def user_stream_url(self, listen_key):
        # USD-M Futures Testnet uses the same stream host configured for market data.
        return self.ws_base_url.rstrip("/") + "/ws/" + listen_key if hasattr(self, "ws_base_url") else "wss://stream.binancefuture.com/ws/" + listen_key
