import asyncio
import time
from decimal import Decimal
import pytest

from app.execution.lifecycle import reconstruct_opened_at_ms
from app.paper import ExecutionState, InternalPosition, BinancePaperExecutionAdapter


def test_reconstruct_open_time_survives_partial_closes():
    trades = [
        {"id": 1, "time": 1000, "side": "BUY", "qty": "1"},
        {"id": 2, "time": 2000, "side": "BUY", "qty": "1"},
        {"id": 3, "time": 3000, "side": "SELL", "qty": "0.5"},
    ]
    assert reconstruct_opened_at_ms(trades, 1.5) == 1000


def test_reconstruct_open_time_changes_after_reversal():
    trades = [
        {"id": 1, "time": 1000, "side": "BUY", "qty": "1"},
        {"id": 2, "time": 2000, "side": "SELL", "qty": "1.5"},
        {"id": 3, "time": 3000, "side": "SELL", "qty": "0.5"},
    ]
    assert reconstruct_opened_at_ms(trades, -1.0) == 2000


def test_execution_state_uses_trade_timestamp_on_new_position():
    s = ExecutionState()
    s.apply_trade_update({"E": 900, "o": {"s": "BTCUSDT", "S": "BUY", "x": "TRADE", "l": "0.1", "T": 800}})
    s.apply_account_update({"E": 1000, "a": {"P": [{"s": "BTCUSDT", "pa": "0.1", "ep": "100", "mp": "101", "up": "0", "iw": "10", "mt": "ISOLATED", "l": "10"}]}})
    assert s.positions["BTCUSDT"].opened_at_ms == 800


def test_execution_state_preserves_open_time_on_partial_add():
    s = ExecutionState()
    s.positions["BTCUSDT"] = InternalPosition("BTCUSDT", Decimal("0.1"), opened_at_ms=800)
    s.apply_trade_update({"E": 1500, "o": {"s": "BTCUSDT", "S": "BUY", "x": "TRADE", "l": "0.1", "T": 1500}})
    s.apply_account_update({"E": 1600, "a": {"P": [{"s": "BTCUSDT", "pa": "0.2", "ep": "100", "mp": "101", "up": "0", "iw": "10", "mt": "ISOLATED", "l": "10"}]}})
    assert s.positions["BTCUSDT"].opened_at_ms == 800


def test_exchange_recovery_helper_uses_shared_reconstruction():
    class Rest:
        async def user_trades(self, symbol, **kw):
            return [
                {"id": 1, "time": 1000, "side": "BUY", "qty": "1"},
                {"id": 2, "time": 2000, "side": "SELL", "qty": "0.25"},
            ]

    adapter = BinancePaperExecutionAdapter.__new__(BinancePaperExecutionAdapter)
    adapter.rest = Rest()
    got = asyncio.run(adapter._recover_position_opened_at_from_exchange("BTCUSDT", 0.75))
    assert got == 1000


def test_exchange_recovery_paginates_beyond_1000_trades():
    class Rest:
        def __init__(self):
            self.calls = []
        async def user_trades(self, symbol, **kw):
            self.calls.append(dict(kw))
            if len(self.calls) == 1:
                # Opening trade is older than the newest 1000 rows.
                return [{"id": i, "time": 3000000 - i, "side": "BUY", "qty": "0.001"} for i in range(1000, 0, -1)]
            if len(self.calls) == 2:
                return [
                    {"id": 1, "time": 1000, "side": "BUY", "qty": "0.75"},
                ]
            return []

    adapter = BinancePaperExecutionAdapter.__new__(BinancePaperExecutionAdapter)
    adapter.rest = Rest()
    got = asyncio.run(adapter._recover_position_opened_at_from_exchange("BTCUSDT", 0.75))
    assert got == 1000
    assert len(adapter.rest.calls) == 2
    assert adapter.rest.calls[1]["endTime"] == 2998999


def test_unknown_open_time_is_distinguished_from_known_zero_position():
    p = InternalPosition("BTCUSDT", Decimal("0.5"), opened_at_ms=0, open_time_known=False)
    s = ExecutionState()
    s.positions["BTCUSDT"] = p
    s.account_snapshot = {"_equity": 1000.0, "_source": "authenticated_user_stream", "_authoritative": True, "_last_event_time_ms": 1000}
    s.last_user_stream_message_time_ms = 1000
    import pytest
    snap = s.account_snapshot_for("BTCUSDT", now_ms=1100, max_age_ms=1000)
    assert snap.open_time_known is False
    assert snap.time_in_position_seconds == 0.0


def test_exchange_recovery_returns_unknown_when_history_not_fully_exhausted():
    class Rest:
        async def user_trades(self, symbol, **kw):
            return [{"id": i, "time": 10_000_000 - i, "side": "BUY", "qty": "0.001"} for i in range(1000, 0, -1)]

    adapter = BinancePaperExecutionAdapter.__new__(BinancePaperExecutionAdapter)
    adapter.rest = Rest()
    got = asyncio.run(adapter._recover_position_opened_at_from_exchange("BTCUSDT", 0.5, max_pages=1))
    assert got is None


def test_restart_preserves_six_hour_position_age_from_local_lifecycle():
    now_ms = int(time.time() * 1000)
    opened_at_ms = now_ms - 6 * 60 * 60 * 1000

    class Rest:
        base_url = "https://testnet.binancefuture.com"
        session = object()
        async def account(self):
            return {"totalWalletBalance": "1000"}
        async def position_risk(self):
            return [{"symbol": "BTCUSDT", "positionAmt": "0.1", "entryPrice": "100",
                     "markPrice": "101", "unRealizedProfit": "1", "leverage": "5"}]
        async def user_trades(self, *_args, **_kwargs):
            raise AssertionError("local lifecycle record should be used first")

    class LifecycleStore:
        async def load_position_open_state(self, mode, symbol):
            assert (mode, symbol) == ("PAPER_TESTNET", "BTCUSDT")
            return opened_at_ms, True

    adapter = BinancePaperExecutionAdapter(Rest(), db_logger=LifecycleStore())
    asyncio.run(adapter.bootstrap_state())  # restart bootstrap
    adapter.ws_connected = True
    snapshot = adapter.state.account_snapshot_for(
        "BTCUSDT", now_ms=now_ms, max_age_ms=30_000, allow_bootstrap=True, ws_connected=True,
    )
    assert snapshot.open_time_known is True
    assert snapshot.time_in_position_seconds == pytest.approx(6 * 60 * 60, abs=1.0)
