import asyncio
import json
from decimal import Decimal

import pytest

from app.paper import ExecutionState, BinancePaperExecutionAdapter, InternalPosition


def test_user_stream_liveness_and_account_state_change_are_separate():
    s = ExecutionState()
    s.note_user_stream_message(received_at_ms=1000)
    s.apply_account_update({'E': 900, 'a': {'B': [{'a': 'USDT', 'wb': '1000'}]}})
    assert s.last_user_stream_message_time_ms == 1000
    assert s.last_account_state_update_time_ms == 900
    assert s.account_snapshot['_last_user_stream_message_time_ms'] == 1000


def test_bootstrap_is_allowed_only_once_user_ws_is_healthy():
    s = ExecutionState()
    s.account_snapshot = {
        '_source': 'rest_bootstrap', '_authoritative': False,
        '_bootstrap_time_ms': 1000, '_equity': 1000.0,
    }
    assert not s.is_account_state_fresh(now_ms=1100, max_age_ms=30000, allow_bootstrap=True, ws_connected=False)
    assert s.is_account_state_fresh(now_ms=1100, max_age_ms=30000, allow_bootstrap=True, ws_connected=True)


def test_account_state_freshness_uses_user_stream_silence_not_account_change_age():
    s = ExecutionState()
    s.note_user_stream_message(received_at_ms=1000)
    s.apply_account_update({'E': 1000, 'a': {'B': [{'a': 'USDT', 'wb': '1000'}]}})
    # No account change for 10s, but user-stream communication is recent enough under this threshold.
    assert s.is_account_state_fresh(now_ms=9000, max_age_ms=10000, ws_connected=True, require_user_stream_health=True)


def test_redis_hot_state_projection_is_applied_monotonically():
    s = ExecutionState()
    payload1 = {
        'updated_at_ms': 2000, 'source': 'authenticated_user_stream', 'authoritative': True,
        'last_event_time_ms': 2000,
        'account': {'_equity': 1050.0, '_last_event_time_ms': 2000,
                    '_last_user_stream_message_time_ms': 2000,
                    '_source': 'authenticated_user_stream', '_authoritative': True},
        'positions': {'BTCUSDT': {'symbol': 'BTCUSDT', 'position_amt': '1', 'mark_price': '100',
                                  'unrealized_pnl': '50', 'leverage': '2', 'opened_at_ms': 1500,
                                  'open_time_known': True}},
    }
    assert s.apply_hot_state_payload(payload1)
    assert s.positions['BTCUSDT'].unrealized_pnl == Decimal('50')
    payload0 = dict(payload1)
    payload0['updated_at_ms'] = 1000
    payload0['account'] = dict(payload1['account'])
    payload0['account']['_equity'] = 1.0
    assert not s.apply_hot_state_payload(payload0)
    assert s.account_snapshot['_equity'] == 1050.0


def test_reconciliation_does_not_overwrite_authoritative_user_stream_state():
    class Rest:
        async def account(self):
            return {'totalMarginBalance': '999', 'totalWalletBalance': '999'}

    adapter = BinancePaperExecutionAdapter.__new__(BinancePaperExecutionAdapter)
    adapter.rest = Rest()
    adapter.state = ExecutionState()
    adapter.state.account_snapshot = {
        '_source': 'authenticated_user_stream', '_authoritative': True,
        '_equity': 1234.0, '_last_event_time_ms': 5000,
    }
    adapter.state.last_user_stream_message_time_ms = 5000
    got = asyncio.run(adapter.refresh_account_state())
    assert got['totalMarginBalance'] == '999'
    assert adapter.state.account_snapshot['_equity'] == 1234.0
    assert adapter.state.account_snapshot['_source'] == 'authenticated_user_stream'
