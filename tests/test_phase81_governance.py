from pathlib import Path
import pytest
from app.governance.capital import CapitalRampController
from app.governance.challenger import ChallengerPipeline
from app.risk.manager import RiskManager, RiskConfig


def test_initial_ramp_is_ten_percent_and_enforced(tmp_path):
    r=CapitalRampController(tmp_path/'ramp.json')
    r.activate_initial(approved_capital=10000, reviewer='human', human_approved=True)
    assert r.state.stage == 0
    assert r.state.target_fraction == .10
    assert r.max_notional(10000) == 1000
    r.assert_order_allowed(current_notional=500, additional_notional=400, equity=10000)
    with pytest.raises(PermissionError):
        r.assert_order_allowed(current_notional=500, additional_notional=600, equity=10000)


def test_cannot_skip_ramp_stage(tmp_path):
    r=CapitalRampController(tmp_path/'ramp.json')
    r.activate_initial(approved_capital=10000, reviewer='human', human_approved=True)
    with pytest.raises(PermissionError): r.validate_runtime_stage(1)
    assert r.can_advance(days_at_stage=6,pnl_positive=True,max_drawdown=.01,max_allowed_drawdown=.15) is False
    assert r.can_advance(days_at_stage=7,pnl_positive=True,max_drawdown=.01,max_allowed_drawdown=.15) is True
    r.approve_advance(reviewer='human',human_approved=True,pnl_positive=True,max_drawdown=.01)
    assert r.state.stage == 1 and r.state.target_fraction == .25


def test_risk_vetoes_ramp_overage():
    r=RiskManager(RiskConfig())
    class Ramp:
        def assert_order_allowed(self, **kwargs): raise PermissionError
    d=r.check_action(0,position_qty=0,equity=10000,mark_price=100,leverage=1,concurrent_positions=0,requested_qty=2,capital_ramp=Ramp())
    assert d.allowed is False and 'capital_ramp_limit' in d.reasons


def test_challenger_pipeline_never_promotes(tmp_path):
    c=ChallengerPipeline(tmp_path/'challenger.json')
    import sys, asyncio
    ok=asyncio.run(c.run(f'{sys.executable} -c \"print(42)\"','manual_test'))
    assert ok
    assert c.status().status == 'READY_FOR_REVIEW'
    assert c.status().requires_human_promotion is True
