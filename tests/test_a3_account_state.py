import asyncio
import ast
import json
from decimal import Decimal
from pathlib import Path

from app.paper import ExecutionState, InternalPosition, BinancePaperExecutionAdapter, PaperTradingEngine


def test_execution_state_account_update_is_authoritative_and_updates_equity():
    state = ExecutionState()
    state.positions["BTCUSDT"] = InternalPosition(
        symbol="BTCUSDT", position_amt=Decimal("0.01"), unrealized_pnl=Decimal("12.5"), opened_at_ms=1000
    )
    state.apply_account_update({
        "e": "ACCOUNT_UPDATE", "E": 2000,
        "a": {"B": [{"a": "USDT", "wb": "1000.0"}], "P": [{
            "s": "BTCUSDT", "pa": "0.01", "ep": "50000", "mp": "50100", "up": "12.5", "li": "40000", "mt": "ISOLATED", "l": "3"
        }]}
    })
    assert state.account_snapshot["_source"] == "authenticated_user_stream"
    assert state.account_snapshot["_authoritative"] is True
    assert state.account_snapshot["_equity"] == 1012.5
    assert state.account_snapshot["_last_event_time_ms"] == 2000
    assert state.positions["BTCUSDT"].opened_at_ms == 1000


class _Store:
    def __init__(self): self.data = {}
    async def set(self, key, value): self.data[key] = json.loads(value)


def test_user_stream_state_is_mirrored_to_redis_hot_state():
    async def run():
        store = _Store()
        adapter = object.__new__(BinancePaperExecutionAdapter)
        adapter.state_store = store
        adapter.state_key = "execution:account:PAPER_TESTNET"
        adapter.execution_mode = "PAPER_TESTNET"
        adapter.state = ExecutionState()
        adapter.state.account_snapshot = {"_equity": 1234.0, "_source": "authenticated_user_stream", "_authoritative": True}
        adapter.state.positions["BTCUSDT"] = InternalPosition(symbol="BTCUSDT", position_amt=Decimal("1"), opened_at_ms=123456)
        await adapter._publish_authoritative_state()
        payload = store.data[adapter.state_key]
        assert payload["authoritative"] is True
        assert payload["source"] == "authenticated_user_stream"
        assert payload["positions"]["BTCUSDT"]["opened_at_ms"] == 123456
    asyncio.run(run())


def _function_source(path: str, name: str):
    tree = ast.parse(Path(path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(Path(path).read_text(), node)
    raise AssertionError(name)


def test_paper_engine_steady_state_does_not_call_rest_account():
    source = _function_source("app/paper.py", "_execute_action")
    assert "execution.rest.account" not in source
    assert "await self.execution.rest.account" not in source


def test_live_and_paper_scripts_do_not_refresh_account_in_inference_loop():
    for path in ("scripts/paper_trade.py", "scripts/live_trade.py"):
        text = Path(path).read_text()
        assert "refresh_account_state()" not in text


def test_steady_state_inference_uses_user_stream_when_rest_account_fails():
    class Rest:
        base_url = "https://testnet.binancefuture.com"
        session = object()
        async def account(self):
            raise AssertionError("steady-state inference must not poll REST account state")

    now_ms = 5_000_000
    adapter = BinancePaperExecutionAdapter(Rest(), account_max_age_ms=30_000)
    adapter.ws_connected = True
    adapter.state.user_stream_connected = True
    adapter.state.user_stream_authenticated = True
    adapter.state.last_user_stream_message_time_ms = now_ms
    adapter.state.last_user_stream_transport_activity_time_ms = now_ms
    adapter.state.account_snapshot = {
        "_equity": 1_000.0, "_source": "authenticated_user_stream", "_authoritative": True,
    }
    adapter.state.positions["BTCUSDT"] = InternalPosition(
        "BTCUSDT", position_amt=Decimal("0.1"), mark_price=Decimal("100"),
        leverage=Decimal("2"), opened_at_ms=now_ms - 60_000, open_time_known=True,
    )
    observation = asyncio.run(adapter.account_observation_async("BTCUSDT", now_ms=now_ms))
    assert observation == pytest.approx([0.005, 0.0, 2.0, 200.0, 1 / 60])


def test_user_stream_reconnect_runs_one_rest_account_recovery_before_unblocking_state():
    class Rest:
        base_url = "https://testnet.binancefuture.com"
        session = object()
        def __init__(self):
            self.account_calls = 0
        async def account(self):
            self.account_calls += 1
            return {"totalWalletBalance": "1000"}

    rest = Rest()
    adapter = BinancePaperExecutionAdapter(rest)
    adapter.state.account_snapshot = {
        "_equity": 1_000.0, "_source": "authenticated_user_stream",
        "_authoritative": True, "_recovery_required": True,
    }
    assert asyncio.run(adapter._recover_account_state_after_user_stream_failure())
    assert rest.account_calls == 1
    assert "_recovery_required" not in adapter.state.account_snapshot
