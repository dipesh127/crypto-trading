from decimal import Decimal
from .orderbook import DepthUpdate

def depth(data):
    return DepthUpdate(
      symbol=data["s"].upper(),event_time_ms=int(data["E"]),
      first_update_id=int(data["U"]),final_update_id=int(data["u"]),
      prev_final_update_id=int(data["pu"]) if "pu" in data else None,
      bids=tuple((Decimal(p),Decimal(q)) for p,q in data.get("b",[])),
      asks=tuple((Decimal(p),Decimal(q)) for p,q in data.get("a",[])),
    )
