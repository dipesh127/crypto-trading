import time
import pytest
from app.paper import ExecutionState

def test_equity_uses_fresh_position_updates():
    s=ExecutionState(); now=int(time.time()*1000)
    s.apply_account_update({'E':now,'a':{'B':[{'a':'USDT','wb':'1000'}],'P':[{'s':'BTCUSDT','pa':'1','ep':'100','mp':'150','up':'50','li':'0','iw':'100','mt':'ISOLATED','l':'5'}]}})
    assert s.account_snapshot['_equity']==pytest.approx(1050.0)
    snap=s.account_snapshot_for('BTCUSDT',now_ms=now+100,max_age_ms=1000)
    assert snap.equity==pytest.approx(1050.0)
    assert snap.unrealized_pnl==pytest.approx(50.0)

def test_stale_authoritative_state_rejected():
    s=ExecutionState(); now=int(time.time()*1000)
    s.apply_account_update({'E':now-10000,'a':{'B':[{'a':'USDT','wb':'1000'}]}})
    assert not s.is_account_state_fresh(now_ms=now,max_age_ms=5000)
    with pytest.raises(RuntimeError): s.account_snapshot_for('BTCUSDT',now_ms=now,max_age_ms=5000)

def test_canonical_account_snapshot_mapping_is_used():
    s=ExecutionState(); now=int(time.time()*1000)
    s.apply_account_update({'E':now,'a':{'B':[{'a':'USDT','wb':'1000'}],'P':[{'s':'BTCUSDT','pa':'0.1','ep':'100','mp':'110','up':'1','li':'0','iw':'10','mt':'ISOLATED','l':'2'}]}})
    snap=s.account_snapshot_for('BTCUSDT',now_ms=now+2000,max_age_ms=5000)
    assert snap.position_qty==pytest.approx(0.1)
    assert snap.mark_price==pytest.approx(110)
    assert snap.leverage==pytest.approx(2)
    assert snap.equity==pytest.approx(1001)
