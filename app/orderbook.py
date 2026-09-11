from collections import deque
from decimal import Decimal
from dataclasses import dataclass

@dataclass(frozen=True)
class DepthUpdate:
    symbol:str; event_time_ms:int; first_update_id:int; final_update_id:int
    prev_final_update_id:int|None; bids:tuple; asks:tuple

class OrderBook:
    def __init__(self,symbol): self.symbol=symbol; self.last_update_id=0; self.bids={}; self.asks={}
    def apply(self,u):
        for p,q in u.bids:
            if q==0: self.bids.pop(p,None)
            else: self.bids[p]=q
        for p,q in u.asks:
            if q==0: self.asks.pop(p,None)
            else: self.asks[p]=q
        self.last_update_id=u.final_update_id

class OrderBookReconciler:
    def __init__(self,symbol,max_buffer=10000): self.symbol=symbol; self.buffer=deque(maxlen=max_buffer); self.book=None; self.synced=False; self.resync_required=False
    def push(self,u): self.buffer.append(u)
    def initialize_from_snapshot(self,snapshot):
        self.book=OrderBook(self.symbol); sid=int(snapshot['lastUpdateId']); self.book.last_update_id=sid
        self.book.bids={Decimal(p):Decimal(q) for p,q in snapshot.get('bids',[]) if Decimal(q)!=0}; self.book.asks={Decimal(p):Decimal(q) for p,q in snapshot.get('asks',[]) if Decimal(q)!=0}
        self.synced=False; self.resync_required=False; buffered=list(self.buffer); self.buffer.clear()
        for u in buffered:
            if u.final_update_id<=sid: continue
            if not self.synced:
                if not (u.first_update_id<=sid+1<=u.final_update_id): self.resync_required=True; return
                self.book.apply(u); self.synced=True; continue
            if u.prev_final_update_id is not None and u.prev_final_update_id != self.book.last_update_id:
                self.resync_required=True; self.synced=False; self.push(u); return
            if u.first_update_id!=self.book.last_update_id+1: self.resync_required=True; self.synced=False; self.push(u); return
            self.book.apply(u)
        self.synced=True
    def apply_live(self,u):
        if self.book is None: self.push(u); return
        if u.final_update_id<=self.book.last_update_id: return
        if not self.synced:
            if u.first_update_id<=self.book.last_update_id+1<=u.final_update_id:
                self.book.apply(u); self.synced=True; self.resync_required=False; return
            self.resync_required=True; self.push(u); return
        if u.prev_final_update_id is not None and u.prev_final_update_id != self.book.last_update_id:
            self.synced=False; self.resync_required=True; self.push(u); return
        if u.first_update_id!=self.book.last_update_id+1:
            self.synced=False; self.resync_required=True; self.push(u); return
        self.book.apply(u)
    @property
    def ready(self): return bool(self.book and self.synced and not self.resync_required)
