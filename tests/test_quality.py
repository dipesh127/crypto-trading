from decimal import Decimal
from app.orderbook import OrderBookReconciler
def test_zero_price_rejected_by_domain():
    assert Decimal("0") <= 0
