from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable, Mapping
import math
import pandas as pd
import numpy as np
from .indicators import depth_within_bps, ofi, kyles_lambda, agg_trade_intensity, liquidation_cluster

@dataclass
class BookState:
    bids: dict[float,float]
    asks: dict[float,float]
    last_update_id: int = 0

    def apply(self,bids,asks,final_update_id):
        for p,q in bids:
            p=float(p); q=float(q)
            if q<=0:self.bids.pop(p,None)
            else:self.bids[p]=q
        for p,q in asks:
            p=float(p); q=float(q)
            if q<=0:self.asks.pop(p,None)
            else:self.asks[p]=q
        self.last_update_id=int(final_update_id)

def replay_book(snapshots: pd.DataFrame, updates: pd.DataFrame, start=None, end=None) -> pd.DataFrame:
    """Replay persisted Binance diff-depth updates from the latest usable snapshot.

    Binance does not expose arbitrary historical L2 snapshots via the normal depth REST endpoint,
    so this intentionally replays locally persisted raw snapshots/updates rather than fabricating history.
    """
    if updates.empty: return pd.DataFrame()
    updates=updates.sort_values('event_time')
    snapshots=snapshots.sort_values('snapshot_time') if not snapshots.empty else snapshots
    if start is not None:
        st=pd.Timestamp(start); st=st.tz_localize('UTC') if st.tzinfo is None else st.tz_convert('UTC'); updates=updates[updates.event_time>=st]
    if end is not None:
        et=pd.Timestamp(end); et=et.tz_localize('UTC') if et.tzinfo is None else et.tz_convert('UTC'); updates=updates[updates.event_time<=et]
    if updates.empty:return pd.DataFrame()
    first_ts=updates.event_time.iloc[0]
    eligible=snapshots[snapshots.snapshot_time<=first_ts]
    # Never seed a historical replay from a snapshot that occurs after the requested updates.
    if eligible.empty:return pd.DataFrame()
    snap=eligible.iloc[-1]
    bids={float(x[0]):float(x[1]) for x in snap.bids}; asks={float(x[0]):float(x[1]) for x in snap.asks}; state=BookState(bids,asks,int(snap.last_update_id)); out=[]
    for r in updates.itertuples(index=False):
        state.apply(r.bids,r.asks,r.final_update_id)
        bid=sorted(state.bids.items(),reverse=True); ask=sorted(state.asks.items())
        if not bid or not ask: continue
        bp,bq=bid[0]; ap,aq=ask[0]; mid=(bp+ap)/2
        depth=depth_within_bps([ [p for p,_ in bid] ],[[q for _,q in bid]],[[p for p,_ in ask]],[[q for _,q in ask]],mid_price=mid)
        d=depth.iloc[0].to_dict()
        d.update({'event_time':r.event_time,'best_bid':bp,'best_ask':ap,'bid_qty':bq,'ask_qty':aq,'microprice':(ap*bq+bp*aq)/(bq+aq) if bq+aq else mid,'spread_abs':ap-bp,'spread_rel':(ap-bp)/mid if mid else np.nan,'last_update_id':state.last_update_id})
        out.append(d)
    return pd.DataFrame(out)

def aggregate_trades(trades: pd.DataFrame, bars: str='1min') -> pd.DataFrame:
    if trades.empty:return pd.DataFrame()
    t=trades.copy(); t['trade_time']=pd.to_datetime(t['trade_time'],utc=True); t['price']=pd.to_numeric(t['price']); t['quantity']=pd.to_numeric(t['quantity']); t['signed_qty']=np.where(t['buyer_is_maker'].astype(bool),-t['quantity'],t['quantity']); t['notional']=t['price']*t['quantity']
    g=t.set_index('trade_time').groupby(pd.Grouper(freq=bars))
    out=g.agg(trade_count=('agg_id','count'),trade_notional=('notional','sum'),aggressive_buy_qty=('signed_qty',lambda x: float(x[x>0].sum())),aggressive_sell_qty=('signed_qty',lambda x: float(-x[x<0].sum())))
    out['signed_volume']=g['signed_qty'].sum(); return out

def merge_microstructure(book_rows: pd.DataFrame, trade_rows: pd.DataFrame, liquidations: pd.DataFrame|None=None) -> pd.DataFrame:
    if book_rows.empty:return pd.DataFrame()
    b=book_rows.copy(); b['event_time']=pd.to_datetime(b['event_time'],utc=True); b=b.set_index('event_time').sort_index().resample('1min').last().ffill()
    t=aggregate_trades(trade_rows).reindex(b.index).fillna(0) if trade_rows is not None else pd.DataFrame(index=b.index)
    out=b.join(t,how='left').fillna(0)
    out['ofi_1m']=ofi(out['best_bid'],out['best_ask'],out['bid_qty'],out['ask_qty'])
    out['kyle_lambda']=kyles_lambda(out['microprice'],out.get('signed_volume',pd.Series(0,index=out.index)),window=50)
    trade_ts=list(pd.to_datetime(trade_rows.trade_time,utc=True)) if trade_rows is not None and not trade_rows.empty else []
    if trade_ts: out['trade_intensity']=agg_trade_intensity(out.index,trade_ts,decay_seconds=60.0)
    else: out['trade_intensity']=0.0
    if liquidations is not None and not liquidations.empty:
        l=liquidations.copy(); l['event_time']=pd.to_datetime(l['event_time'],utc=True); l['notional']=pd.to_numeric(l.get('original_quantity',0),errors='coerce').fillna(0)*pd.to_numeric(l.get('average_price',l.get('price',0)),errors='coerce').fillna(0); long=l.assign(_long=np.where(l['side'].astype(str).str.upper().eq('BUY'),l['notional'],0)).set_index('event_time').resample('1min')['_long'].sum(); short=l.assign(_short=np.where(l['side'].astype(str).str.upper().eq('SELL'),l['notional'],0)).set_index('event_time').resample('1min')['_short'].sum(); out=out.join(liquidation_cluster(long.reindex(out.index).fillna(0),short.reindex(out.index).fillna(0),20))
    return out
