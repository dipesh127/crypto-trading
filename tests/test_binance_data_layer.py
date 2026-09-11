import asyncio
import json
import time
import pytest

from app.rate_limit import BinanceLimiter, TokenBucket
from app.binance import BinanceREST
from app.monitoring import binance_rate_limit_state, observe_binance_http_status


def test_raw_bucket_exhaustion_and_refill():
    async def run():
        limiter = BinanceLimiter(raw_requests_per_minute=2, order_requests_per_minute=10, weight_per_minute=10)
        await limiter.acquire(); await limiter.acquire()
        assert limiter.raw_requests.tokens < 0.01
        limiter.raw_requests.updated -= 30
        await limiter.acquire()
        assert limiter.raw_requests.tokens < 1.01
    asyncio.run(run())


def test_weight_raw_and_order_consumed_together():
    async def run():
        limiter = BinanceLimiter(raw_requests_per_minute=10, order_requests_per_minute=10, weight_per_minute=20)
        await limiter.acquire(weight=4, order_count=2)
        assert limiter.raw_requests.tokens < 9
        assert limiter.weight.tokens < 17
        assert limiter.orders.tokens < 9
    asyncio.run(run())


def test_header_feedback_updates_all_buckets():
    async def run():
        limiter = BinanceLimiter(raw_requests_per_minute=10, order_requests_per_minute=10, weight_per_minute=20)
        limiter.observe_headers({'X-MBX-USED-WEIGHT-1M':'7','X-MBX-ORDER-COUNT-1M':'3','X-MBX-USED-RAW-REQUESTS-1M':'4'})
        await asyncio.sleep(0)
        assert limiter.weight.tokens == pytest.approx(13, abs=.1)
        assert limiter.orders.tokens == pytest.approx(7, abs=.1)
        assert limiter.raw_requests.tokens == pytest.approx(6, abs=.1)
    asyncio.run(run())


def test_rate_limit_telemetry_is_observable_and_persisted():
    class Store:
        value = None
        async def set(self, key, value, ex):
            assert key == "telemetry:binance_rate_limit"
            assert ex > 0
            self.value = value

    async def run():
        store = Store()
        rest = BinanceREST("https://example.invalid", state_store=store,
                           raw_requests_per_minute=10, order_requests_per_minute=20,
                           weight_per_minute=30)
        rest.limiter.observe_headers({"X-MBX-USED-WEIGHT-1M": "9", "X-MBX-ORDER-COUNT-1M": "4", "X-MBX-USED-RAW-REQUESTS-1M": "3"})
        await asyncio.sleep(0)
        observe_binance_http_status(429)
        observe_binance_http_status(418)
        await rest._persist_rate_limit_state()
        state = json.loads(store.value)
        assert state["weight_remaining"] == pytest.approx(21, abs=.1)
        assert state["orders_remaining"] == pytest.approx(16, abs=.1)
        assert state["raw_remaining"] == pytest.approx(7, abs=.1)
        assert state["429_total"] >= 1 and state["418_total"] >= 1
    asyncio.run(run())
