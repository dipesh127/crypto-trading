import math
from app.risk import RiskConfig, RiskManager, fixed_fractional_size, fractional_kelly_size, atr_position_size, parametric_var, expected_shortfall, psi, kl_divergence, PromotionChecklist, CapitalRamp

def test_sizing():
    assert fixed_fractional_size(10000,.01,100)==1
    assert fractional_kelly_size(10000,.6,2,.5)>0
    assert atr_position_size(10000,.01,50,2)==1

def test_tail_and_drift():
    r=[.01,-.01,.02,-.02,.0]*20
    assert parametric_var(r,.95)>=0
    assert expected_shortfall(r,.95)>=0.02
    assert psi(r,r)==0
    assert kl_divergence(r,r)==0

def test_daily_loss_and_veto():
    rm=RiskManager(RiskConfig(daily_loss_limit_fraction=.02,flatten_on_connectivity_failure=True))
    rm.observe(equity=10000,ws_connected=True)
    rm.observe(equity=9700,ws_connected=True)
    d=rm.check_action(0,position_qty=0,equity=9700,mark_price=100,leverage=1,concurrent_positions=0)
    assert not d.allowed and d.action==3 and 'daily_loss_limit' in d.reasons

def test_connectivity_flatten():
    from datetime import datetime, timezone, timedelta
    rm=RiskManager(RiskConfig(ws_disconnect_seconds=10,flatten_on_connectivity_failure=True))
    t=datetime.now(timezone.utc); rm.observe(equity=10000,now=t,ws_connected=True)
    rm.observe(equity=10000,now=t+timedelta(seconds=1),ws_connected=False)
    rm.observe(equity=10000,now=t+timedelta(seconds=11),ws_connected=False)
    d=rm.check_action(0,position_qty=1,equity=10000,mark_price=100,leverage=1,concurrent_positions=1)
    assert d.action==3 and d.flatten

def test_promotion_is_manual():
    ok,checks=PromotionChecklist().evaluate(profitable_weeks=8,trade_count=250,max_drawdown=.10,human_signoff=False)
    assert not ok and not checks['human_signoff']
    assert CapitalRamp().target_fraction(0)==.10
