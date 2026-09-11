from __future__ import annotations
import asyncio
import inspect
from collections import deque
import json
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from app.features.pipeline import FeaturePipeline
from app.features.normalization import TrainOnlyScaler
from app.features.checkpoint import code_fingerprint, schema_hash, validate_checkpoint_runtime

class BinanceFeatureStore:
    """Real-time feature store backed by Redis market streams/hot state.

    REST market endpoints are deliberately not used in the normal inference path. A running
    MarketDataIngestion service publishes closed klines, trades and the local order book into Redis;
    PostgreSQL is used only as a historical warm-start fallback when Redis has not accumulated enough
    closed bars yet. Account state is supplied separately by the execution adapter.
    """
    def __init__(self, rest, symbol, intervals=("1m","5m","15m","1h"), max_rows=400,
                 pipeline=None, redis=None, regime_model_path=None, db_pool=None,
                 scaler_state=None, checkpoint_metadata=None, require_scaler=True, cross_asset_symbols=()):
        self.rest=rest; self.symbol=symbol.upper(); self.intervals=tuple(intervals); self.max_rows=max_rows
        self.pipeline=pipeline or FeaturePipeline()
        if regime_model_path: self.pipeline.load_regime(regime_model_path)
        if not self.pipeline.regime_fitted:
            raise RuntimeError('live feature store requires a persisted training-fitted regime model; refusing to fit from live data')
        if checkpoint_metadata is not None:
            validate_checkpoint_runtime(checkpoint_metadata, checkpoint_metadata.get("feature_columns",[]), __import__("pathlib").Path("app/features"))
            self._validate_checkpoint(checkpoint_metadata)
        scaler_state = scaler_state if scaler_state is not None else ((checkpoint_metadata or {}).get('scaler') if checkpoint_metadata else None)
        if require_scaler and not scaler_state:
            raise RuntimeError('live inference requires a training-fitted scaler persisted in checkpoint metadata')
        self.scaler=TrainOnlyScaler.from_state_dict(scaler_state) if scaler_state else None
        self.db_pool=db_pool; self.frames={tf:pd.DataFrame() for tf in self.intervals}; self.cross_asset_symbols=tuple(sorted({x.upper() for x in cross_asset_symbols if x.upper()!=self.symbol})); self.cross_frames={sym:{tf:pd.DataFrame() for tf in self.intervals} for sym in self.cross_asset_symbols}
        self.book={}; self.book_history=deque(maxlen=2000); self.redis=redis; self.trade_events=deque(maxlen=50000); self._lock=asyncio.Lock()

    def _validate_checkpoint(self, meta):
        expected_code=code_fingerprint(__import__('pathlib').Path('app/features'))
        if meta.get('feature_code_sha256') and meta['feature_code_sha256'] != expected_code:
            raise RuntimeError(f"feature-code fingerprint mismatch: checkpoint={meta['feature_code_sha256']} runtime={expected_code}")
        cols=meta.get('feature_columns')
        if cols and meta.get('schema_hash') and meta['schema_hash'] != schema_hash(cols):
            raise RuntimeError('checkpoint feature schema hash is internally inconsistent')

    async def _read_stream(self, stream, count=100000):
        if self.redis is None: return []
        try: return await self.redis.xrevrange(stream,max='+',min='-',count=count)
        except Exception: return []

    async def _load_from_redis(self):
        rows=await self._read_stream('market:kline',max(100000, self.max_rows*len(self.intervals)*max(4,len(self.cross_asset_symbols)+1)))
        wanted={self.symbol,*self.cross_asset_symbols}; grouped={(sym,tf):[] for sym in wanted for tf in self.intervals}
        for _,fields in reversed(rows):
            try: d=json.loads(fields.get('data','{}'))
            except Exception: continue
            sym=str(d.get('symbol',d.get('s',''))).upper(); tf=d.get('interval')
            if sym not in wanted or tf not in self.intervals or not d.get('closed',d.get('x',False)): continue
            grouped[(sym,tf)].append(d)
        for sym in wanted:
            target=self.frames if sym==self.symbol else self.cross_frames[sym]
            for tf in self.intervals:
                vals=grouped[(sym,tf)][-self.max_rows:]
                if not vals: continue
                d=pd.DataFrame(vals); d['open_time']=pd.to_datetime(d['open_time'],unit='ms',utc=True); d=d.set_index('open_time').sort_index()
                for c in ('open','high','low','close','volume','quote_volume','trade_count','taker_buy_base_volume','taker_buy_quote_volume'):
                    if c in d: d[c]=pd.to_numeric(d[c],errors='coerce')
                target[tf]=d
        # Hot order-book state is authoritative for current microstructure.
        try:
            raw=await self.redis.get(f'market:book:{self.symbol}')
            if raw:
                self.book=json.loads(raw)
        except Exception: pass
        trades=await self._read_stream('market:trade',50000)
        events=[]
        for _,fields in reversed(trades):
            try: d=json.loads(fields.get('data','{}'))
            except Exception: continue
            if str(d.get('s',d.get('symbol',''))).upper()==self.symbol:
                ms=d.get('T',d.get('time',d.get('E')))
                if ms is not None: events.append(pd.to_datetime(int(ms),unit='ms',utc=True))
        self.trade_events=deque(events,maxlen=50000)
        bt=await self._read_stream('market:bookTicker',2000)
        for _,fields in reversed(bt):
            try: d=json.loads(fields.get('data','{}'))
            except Exception: continue
            if str(d.get('s',d.get('symbol',''))).upper()==self.symbol:
                self.book.update({'bid_price':float(d.get('b',d.get('bidPrice',0))), 'ask_price':float(d.get('a',d.get('askPrice',0))),
                                  'bid_qty':float(d.get('B',d.get('bidQty',0))), 'ask_qty':float(d.get('A',d.get('askQty',0)))})
                break

    async def _load_from_db(self):
        if self.db_pool is None: return
        async with self.db_pool.acquire() as c:
            for symbol,target in [(self.symbol,self.frames),*[(sym,self.cross_frames[sym]) for sym in self.cross_asset_symbols]]:
                for tf in self.intervals:
                    rows=await c.fetch("SELECT open_time,open,high,low,close,volume,quote_volume,trade_count,taker_buy_base_volume,taker_buy_quote_volume FROM market.klines WHERE symbol=$1 AND interval=$2 AND is_closed=TRUE ORDER BY open_time DESC LIMIT $3",symbol,tf,self.max_rows)
                    if rows:
                        d=pd.DataFrame([dict(r) for r in rows]); d['open_time']=pd.to_datetime(d['open_time'],utc=True); d=d.set_index('open_time').sort_index(); target[tf]=d
            tr=await c.fetch("SELECT trade_time FROM market.trades_raw WHERE symbol=$1 ORDER BY trade_time DESC LIMIT 50000",self.symbol)
            self.trade_events=deque([r['trade_time'] for r in reversed(tr)],maxlen=50000)
            b=await c.fetchrow("SELECT bids,asks FROM market.orderbook_snapshots WHERE symbol=$1 ORDER BY snapshot_time DESC LIMIT 1",self.symbol)
            if b and not self.book.get('bid_prices'):
                try:
                    bids=json.loads(b['bids']) if isinstance(b['bids'],str) else b['bids']; asks=json.loads(b['asks']) if isinstance(b['asks'],str) else b['asks']
                    self.book.update({'bid_prices':[float(x[0]) for x in bids], 'bid_qtys':[float(x[1]) for x in bids], 'ask_prices':[float(x[0]) for x in asks], 'ask_qtys':[float(x[1]) for x in asks]})
                except Exception: pass

    async def refresh(self):
        async with self._lock:
            await self._load_from_redis()
            if any(len(self.frames[tf]) < self.max_rows//2 for tf in self.intervals):
                await self._load_from_db()
            now=pd.Timestamp.now(tz='UTC')
            if self.book:
                self.book_history.append((now,dict(self.book)))

    def frame(self, feature_columns):
        frames={}
        for tf,d in self.frames.items():
            x=d.copy()
            if self.book_history:
                micro=pd.DataFrame([v for _,v in self.book_history],index=[t for t,_ in self.book_history])
                micro=micro[~micro.index.duplicated(keep='last')].sort_index()
                x=x.join(micro.reindex(x.index,method='ffill'),how='left')
            if tf=='1m' and self.book.get('bid_prices') and len(x):
                for col in ('bid_prices','bid_qtys','ask_prices','ask_qtys'): x.loc[x.index[-1],col]=[self.book[col]]
            frames[tf]=x
        out=self.pipeline.compute_multitimeframe(frames,fit_regime=False,trade_events=list(self.trade_events))
        if self.cross_asset_symbols:
            cross_frames={self.symbol:frames.get('1m',pd.DataFrame())}
            for sym in self.cross_asset_symbols:
                if len(self.cross_frames[sym].get('1m',pd.DataFrame())): cross_frames[sym]=self.cross_frames[sym]['1m']
            if len(cross_frames)>=2 and all(len(x)>0 for x in cross_frames.values()):
                try:
                    cross=self.pipeline.compute_cross_asset(cross_frames,btc_symbol='BTCUSDT',window=60,fit_regime=False).get(self.symbol)
                    for col in ('btc_correlation','btc_beta'):
                        if cross is not None and col in cross: out[f'{col}_1m']=cross[col].reindex(out.index)
                    for col in cross.columns:
                        if col.startswith('xs_'): out[f'{col}_1m']=cross[col].reindex(out.index)
                except Exception:
                    pass
        out=out.replace([np.inf,-np.inf],np.nan).ffill()
        if self.scaler:
            cols=[c for c in out.columns if c in self.scaler.columns]
            scaled=self.scaler.transform(out[cols]); out.loc[:,cols]=scaled[cols]
        return out.dropna(subset=[c for c in feature_columns if c in out.columns])

    def latest_market_volatility_stats(self, window=60):
        d=self.frames.get('1m')
        if d is None or len(d)<max(3,window+1): return None,None,None
        close=pd.to_numeric(d['close'],errors='coerce').dropna(); r=np.log(close).diff().dropna().to_numpy(dtype=float)
        if len(r)<window: return None,None,None
        short=float(np.std(r[-window:],ddof=1)); vols=[float(np.std(r[i-window:i],ddof=1)) for i in range(window,len(r)+1) if len(r[i-window:i])>1]
        if len(vols)<2: return short,None,None
        return short,float(np.mean(vols)),float(np.std(vols,ddof=1))

    async def get_observation(self, feature_columns, window=60, account=None):
        await self.refresh(); frame=self.frame(feature_columns)
        missing=set(feature_columns)-set(frame.columns)
        if missing: raise ValueError(f'checkpoint features unavailable in real-time pipeline: {sorted(missing)}')
        if len(frame)<window: raise RuntimeError(f'need {window} complete rows; got {len(frame)}')
        market=np.nan_to_num(frame.iloc[-window:][list(feature_columns)].to_numpy(dtype=np.float32),nan=0.0,posinf=0.0,neginf=0.0)
        if account:
            provided = account()
            if inspect.isawaitable(provided):
                provided = await provided
            acct=np.asarray(provided,dtype=np.float32)
        else:
            acct=np.zeros(5,dtype=np.float32)
        return {'market':market,'account':acct}
