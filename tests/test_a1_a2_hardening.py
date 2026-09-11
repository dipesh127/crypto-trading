from decimal import Decimal
import pytest

from app.paper import ExecutionState


def _trade(symbol, ts, side, qty):
    return {"o": {"x": "TRADE", "s": symbol, "T": ts, "S": side, "l": str(qty)}}


def _account(symbol, qty, ts, *, ep="100", mp="100", up="0", lev="5"):
    return {
        "E": ts,
        "a": {
            "B": [{"a": "USDT", "wb": "1000"}],
            "P": [{"s": symbol, "pa": str(qty), "ep": ep, "mp": mp, "up": up, "l": lev, "li": "0", "iw": "0", "mt": "ISOLATED"}],
        },
    }


def test_pending_open_timestamp_keeps_earliest_fill_before_account_update():
    s = ExecutionState()
    s.apply_trade_update(_trade("BTCUSDT", 1000, "BUY", "0.2"))
    s.apply_trade_update(_trade("BTCUSDT", 1001, "BUY", "0.3"))
    s.apply_trade_update(_trade("BTCUSDT", 1002, "BUY", "0.5"))
    s.apply_account_update(_account("BTCUSDT", "1.0", 1003))
    p = s.positions["BTCUSDT"]
    assert p.opened_at_ms == 1000
    assert p.open_time_known is True


def test_unknown_open_time_refuses_live_observation():
    s = ExecutionState()
    s.account_snapshot = {
        "_equity": 1000.0,
        "_source": "authenticated_user_stream",
        "_authoritative": True,
        "_last_event_time_ms": 1000,
        "_last_user_stream_message_time_ms": 1000,
    }
    s.last_user_stream_message_time_ms = 1000
    s.positions["BTCUSDT"] = type("P", (), {
        "position_amt": Decimal("1"), "mark_price": Decimal("100"),
        "unrealized_pnl": Decimal("0"), "leverage": Decimal("5"),
        "opened_at_ms": 0, "open_time_known": False,
    })()
    with pytest.raises(RuntimeError, match="open time is unknown"):
        s.account_snapshot_for("BTCUSDT", now_ms=1001, max_age_ms=5000, ws_connected=True, require_user_stream_health=True, require_open_time_known=True)


def test_unknown_open_time_allowed_only_when_explicitly_disabled():
    s = ExecutionState()
    s.account_snapshot = {
        "_equity": 1000.0,
        "_source": "authenticated_user_stream",
        "_authoritative": True,
        "_last_event_time_ms": 1000,
        "_last_user_stream_message_time_ms": 1000,
    }
    s.last_user_stream_message_time_ms = 1000
    s.positions["BTCUSDT"] = type("P", (), {
        "position_amt": Decimal("1"), "mark_price": Decimal("100"),
        "unrealized_pnl": Decimal("0"), "leverage": Decimal("5"),
        "opened_at_ms": 0, "open_time_known": False,
    })()
    snap = s.account_snapshot_for("BTCUSDT", now_ms=1001, max_age_ms=5000, ws_connected=True,
                                  require_user_stream_health=True, require_open_time_known=False)
    assert snap.open_time_known is False
    assert snap.time_in_position_seconds == 0.0
