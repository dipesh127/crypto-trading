import asyncio
import json
import time
from app.paper import ExecutionState, BinancePaperExecutionAdapter


def test_transport_activity_is_distinct_from_account_change():
    s = ExecutionState()
    s.note_user_stream_message(received_at_ms=1000)
    s.note_user_stream_transport_activity(received_at_ms=9000)
    s.user_stream_connected = True
    s.user_stream_authenticated = True
    s.account_snapshot = {'_source':'authenticated_user_stream','_authoritative':True,'_last_event_time_ms':1000}
    assert s.is_account_state_fresh(now_ms=9500, max_age_ms=10000, ws_connected=True, require_user_stream_health=True, transport_max_age_ms=1000)
    assert not s.is_account_state_fresh(now_ms=11501, max_age_ms=10000, ws_connected=True, require_user_stream_health=True, transport_max_age_ms=1000)


def test_source_priority_prevents_rest_from_overwriting_user_stream():
    s=ExecutionState()
    s._accept_state_version(source_priority=30,event_time_ms=1000)
    assert not s._accept_state_version(source_priority=10,event_time_ms=999999999)


def test_unknown_transport_state_is_rejected_when_health_required():
    s=ExecutionState()
    s.account_snapshot={'_source':'authenticated_user_stream','_authoritative':True,'_last_event_time_ms':1000}
    s.user_stream_connected=False
    s.user_stream_authenticated=False
    s.last_user_stream_message_time_ms=1000
    s.last_user_stream_transport_activity_time_ms=1000
    assert not s.is_account_state_fresh(now_ms=1100, max_age_ms=5000, ws_connected=False, require_user_stream_health=True, transport_max_age_ms=5000)


def test_quiet_account_is_fresh_when_transport_heartbeat_is_healthy():
    s = ExecutionState()
    s.user_stream_connected = True
    s.user_stream_authenticated = True
    s.account_snapshot = {"_source":"authenticated_user_stream", "_authoritative":True, "_last_event_time_ms":1000}
    s.last_account_state_update_time_ms = 1000
    s.last_user_stream_message_time_ms = 1000
    s.last_user_stream_transport_activity_time_ms = 10000
    assert s.is_account_state_fresh(now_ms=20000, max_age_ms=5000, ws_connected=True, require_user_stream_health=True, transport_max_age_ms=15000)


def test_rest_reconciliation_cannot_override_user_stream_even_when_rest_timestamp_is_newer():
    s = ExecutionState()
    assert s._accept_state_version(source_priority=30, event_time_ms=1000)
    assert not s._accept_state_version(source_priority=10, event_time_ms=9999999999)


def test_bootstrap_hot_state_is_not_marked_authoritative():
    class FakeStore:
        def __init__(self): self.value = None
        async def set(self, key, value): self.value = json.loads(value)
    store=FakeStore()
    adapter=BinancePaperExecutionAdapter.__new__(BinancePaperExecutionAdapter)
    adapter.execution_mode='PAPER_TESTNET'; adapter.state=ExecutionState(); adapter.state_store=store; adapter.state_key='k'
    adapter._account_state_freshness_policy={}; adapter._hot_state_updated_at_ms=0
    adapter._user_stream_transport_max_age_ms=30000
    adapter._publish_authoritative_state = BinancePaperExecutionAdapter._publish_authoritative_state.__get__(adapter, BinancePaperExecutionAdapter)
    adapter.state.account_snapshot={'_source':'rest_bootstrap','_authoritative':False,'_equity':1000.0}
    asyncio.run(adapter._publish_authoritative_state())
    assert store.value['source']=='rest_bootstrap'
    assert store.value['authoritative'] is False
