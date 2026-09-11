from decimal import Decimal
from app.orderbook import OrderBookReconciler,DepthUpdate

def u(a,b):
    return DepthUpdate("BTCUSDT",1,a,b,None,((Decimal("100"),Decimal("1")),),((Decimal("101"),Decimal("2")),))

def test_bridge():
    r=OrderBookReconciler("BTCUSDT"); r.push(u(101,102))
    r.initialize_from_snapshot({"lastUpdateId":100,"bids":[["99","1"]],"asks":[["102","1"]]})
    assert r.ready and r.book.last_update_id==102

def test_gap():
    r=OrderBookReconciler("BTCUSDT")
    r.initialize_from_snapshot({"lastUpdateId":100,"bids":[],"asks":[]})
    r.apply_live(u(101,101)); r.apply_live(u(103,103))
    assert r.resync_required and not r.ready

def test_delete():
    r=OrderBookReconciler("BTCUSDT")
    r.initialize_from_snapshot({"lastUpdateId":100,"bids":[["99","1"]],"asks":[]})
    r.apply_live(DepthUpdate("BTCUSDT",1,101,101,None,((Decimal("99"),Decimal("0")),),()))
    assert Decimal("99") not in r.book.bids
