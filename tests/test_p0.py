import asyncio
from datetime import datetime, timezone, timedelta
from app.orderbook import OrderBookReconciler, DepthUpdate
from app.risk.manager import RiskManager, RiskConfig
from app.sim.brackets import Bracket, BracketTable
from app.sim.liquidation import isolated_liquidation_price


def test_orderbook_prev_update_id_forces_resync():
    r=OrderBookReconciler("BTCUSDT")
    r.initialize_from_snapshot({"lastUpdateId":10,"bids":[["100","1"]],"asks":[["101","1"]]})
    r.apply_live(DepthUpdate("BTCUSDT",1,11,11,99,(("100","2"),),()))
    assert r.resync_required and not r.ready


def test_risk_rest_error_is_counted_without_equity():
    r=RiskManager(RiskConfig(rest_error_threshold=2))
    t=datetime.now(timezone.utc)
    r.observe(equity=10000,now=t)
    r.observe(equity=None,now=t+timedelta(seconds=1),rest_error=True)
    reasons=r.observe(equity=None,now=t+timedelta(seconds=2),rest_error=True)
    assert "rest_error_spike" in reasons


def test_binance_piecewise_liquidation_short_and_long():
    b=BracketTable([Bracket(1,20,0,50000,.004,0),Bracket(2,10,50000,100000,.005,50)])
    long=isolated_liquidation_price(100,1000,10000,b,1)
    short=isolated_liquidation_price(100,1000,10000,b,-1)
    assert 0 < long < 100 < short
