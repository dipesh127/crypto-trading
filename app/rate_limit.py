import asyncio, time

class TokenBucket:
    def __init__(self, capacity, refill_per_second):
        self.capacity=capacity; self.tokens=float(capacity); self.refill_per_second=refill_per_second; self.updated=time.monotonic(); self._lock=asyncio.Lock()
    async def acquire(self, tokens=1):
        if tokens > self.capacity: raise ValueError("request exceeds bucket capacity")
        while True:
            async with self._lock:
                now=time.monotonic(); self.tokens=min(self.capacity,self.tokens+(now-self.updated)*self.refill_per_second); self.updated=now
                if self.tokens >= tokens: self.tokens-=tokens; return
                wait=(tokens-self.tokens)/self.refill_per_second
            await asyncio.sleep(wait)
    async def observe_used(self, used):
        if used is None: return
        async with self._lock:
            now=time.monotonic(); self.tokens=min(self.capacity,self.tokens+(now-self.updated)*self.refill_per_second); self.updated=now
            self.tokens=min(self.tokens,max(0.0,self.capacity-float(used)))

class BinanceLimiter:
    def __init__(self, *, weight_per_minute=2400, order_requests_per_minute=1200, raw_requests_per_minute=1200):
        self.weight=TokenBucket(weight_per_minute,weight_per_minute/60)
        self.orders=TokenBucket(order_requests_per_minute,order_requests_per_minute/60)
        self.raw_requests=TokenBucket(raw_requests_per_minute,raw_requests_per_minute/60)
    async def acquire(self, weight=1, order_count=0, raw_requests=1):
        await self.raw_requests.acquire(raw_requests)
        await self.weight.acquire(weight)
        if order_count: await self.orders.acquire(order_count)
        self._publish()
    def _publish(self):
        try:
            from .monitoring import set_binance_rate_limit_telemetry
            set_binance_rate_limit_telemetry(weight_remaining=self.weight.tokens,orders_remaining=self.orders.tokens,raw_remaining=self.raw_requests.tokens)
        except Exception: pass
    def observe_headers(self, headers):
        """Apply Binance's authoritative minute-usage headers.

        The public method remains non-blocking for callers, while publishing only
        after all bucket values have been updated.
        """
        try:
            loop=asyncio.get_running_loop()
            w=headers.get("X-MBX-USED-WEIGHT-1M"); o=headers.get("X-MBX-ORDER-COUNT-1M")
            raw=headers.get("X-MBX-USED-RAW-REQUESTS-1M") or headers.get("X-MBX-USED-REQUESTS-1M")
            async def apply_feedback():
                await asyncio.gather(
                    self.weight.observe_used(float(w)) if w is not None else asyncio.sleep(0),
                    self.orders.observe_used(float(o)) if o is not None else asyncio.sleep(0),
                    self.raw_requests.observe_used(float(raw)) if raw is not None else asyncio.sleep(0),
                )
                self._publish()
            loop.create_task(apply_feedback())
        except RuntimeError: pass
