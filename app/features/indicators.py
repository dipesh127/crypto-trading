from __future__ import annotations
import numpy as np
import pandas as pd

EPS=1e-12

def _s(x): return pd.Series(x, dtype='float64')
def simple_returns(close): return _s(close).pct_change()
def log_returns(close): return np.log(_s(close)/_s(close).shift(1))
def rolling_volatility(close, window=20): return log_returns(close).rolling(window).std(ddof=1)
def zscore(x, window=20):
    s=_s(x); return (s-s.rolling(window).mean())/s.rolling(window).std(ddof=1)
def minmax(x, window=20):
    s=_s(x); lo=s.rolling(window).min(); hi=s.rolling(window).max(); return (s-lo)/(hi-lo).replace(0,np.nan)
def sma(x, window=20): return _s(x).rolling(window).mean()
def ema(x, window=20): return _s(x).ewm(span=window, adjust=False, min_periods=window).mean()
def macd(close, fast=12, slow=26, signal=9):
    efast=ema(close,fast); eslow=ema(close,slow); m=efast-eslow; sig=m.ewm(span=signal,adjust=False,min_periods=signal).mean(); return pd.DataFrame({'macd':m,'signal':sig,'histogram':m-sig})

def atr(high, low, close, window=14):
    h,l,c=map(_s,(high,low,close)); tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1); return tr.ewm(alpha=1/window,adjust=False,min_periods=window).mean()
def rsi(close, window=14):
    d=_s(close).diff(); up=d.clip(lower=0); dn=-d.clip(upper=0); au=up.ewm(alpha=1/window,adjust=False,min_periods=window).mean(); ad=dn.ewm(alpha=1/window,adjust=False,min_periods=window).mean(); rs=au/ad.replace(0,np.nan); out=100-100/(1+rs); out=out.where(ad.ne(0),100); return out

def adx(high, low, close, window=14):
    h,l,c=map(_s,(high,low,close)); up=h.diff(); down=-l.diff(); plus=up.where((up>down)&(up>0),0.0); minus=down.where((down>up)&(down>0),0.0); tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1); atrv=tr.ewm(alpha=1/window,adjust=False,min_periods=window).mean(); pdi=100*plus.ewm(alpha=1/window,adjust=False,min_periods=window).mean()/atrv; mdi=100*minus.ewm(alpha=1/window,adjust=False,min_periods=window).mean()/atrv; dx=100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan); a=dx.ewm(alpha=1/window,adjust=False,min_periods=window).mean(); return pd.DataFrame({'adx':a,'plus_di':pdi,'minus_di':mdi,'dx':dx})

def ichimoku(high, low, close, conversion=9, base=26, span=52, displacement=26, shifted=False, representation=None):
    """Ichimoku values with explicit causal or traditional chart representations.

    ``causal`` contains only values known at the decision timestamp. ``traditional``
    additionally applies the chart displacement (and therefore is visualization-only).
    The historical ``shifted`` argument remains supported for compatibility.
    """
    if representation is None:
        representation='traditional' if shifted else 'causal'
    representation=str(representation).lower()
    if representation not in {'causal','traditional'}:
        raise ValueError("representation must be 'causal' or 'traditional'")
    h,l,c=map(_s,(high,low,close))
    tenkan=(h.rolling(conversion).max()+l.rolling(conversion).min())/2
    kijun=(h.rolling(base).max()+l.rolling(base).min())/2
    span_a=(tenkan+kijun)/2
    span_b=(h.rolling(span).max()+l.rolling(span).min())/2
    if representation=='traditional':
        span_a=span_a.shift(displacement); span_b=span_b.shift(displacement); chikou=c.shift(-displacement)
    else:
        chikou=c.copy()
    return pd.DataFrame({
        'ichimoku_tenkan':tenkan, 'ichimoku_kijun':kijun,
        'ichimoku_span_a':span_a, 'ichimoku_span_b':span_b,
        'ichimoku_chikou':chikou
    })

def ichimoku_representations(high, low, close, conversion=9, base=26, span=52, displacement=26):
    """Return both causal ML-safe and traditional charting Ichimoku representations."""
    causal=ichimoku(high,low,close,conversion,base,span,displacement,representation='causal')
    traditional=ichimoku(high,low,close,conversion,base,span,displacement,representation='traditional')
    return causal.add_suffix('_causal').join(traditional.add_suffix('_traditional'))

def stochastic(high, low, close, window=14, d_window=3):
    h,l,c=map(_s,(high,low,close)); lo=l.rolling(window).min(); hi=h.rolling(window).max(); k=100*(c-lo)/(hi-lo).replace(0,np.nan); return pd.DataFrame({'stoch_k':k,'stoch_d':k.rolling(d_window).mean()})
def cci(high, low, close, window=20):
    tp=(_s(high)+_s(low)+_s(close))/3; ma=tp.rolling(window).mean(); md=tp.rolling(window).apply(lambda x: np.mean(np.abs(x-x.mean())),raw=True); return (tp-ma)/(0.015*md.replace(0,np.nan))
def roc(close, window=12): return _s(close).pct_change(window)*100
def williams_r(high, low, close, window=14):
    h,l,c=map(_s,(high,low,close)); hi=h.rolling(window).max(); lo=l.rolling(window).min(); return -100*(hi-c)/(hi-lo).replace(0,np.nan)
def bollinger(close, window=20, n_std=2):
    c=_s(close); mid=c.rolling(window).mean(); sd=c.rolling(window).std(ddof=1); upper=mid+n_std*sd; lower=mid-n_std*sd; return pd.DataFrame({'bb_mid':mid,'bb_upper':upper,'bb_lower':lower,'bb_bandwidth':(upper-lower)/mid.abs().replace(0,np.nan)})
def keltner(high, low, close, ema_window=20, atr_window=10, multiplier=2):
    c=_s(close); mid=ema(c,ema_window); a=atr(high,low,c,atr_window); return pd.DataFrame({'kc_mid':mid,'kc_upper':mid+multiplier*a,'kc_lower':mid-multiplier*a})
def obv(close, volume):
    c,v=map(_s,(close,volume)); direction=np.sign(c.diff()).fillna(0); return (direction*v).cumsum()
def vwap(high, low, close, volume):
    tp=(_s(high)+_s(low)+_s(close))/3; v=_s(volume); return (tp*v).cumsum()/v.cumsum().replace(0,np.nan)
def cvd(taker_buy_base_volume, volume):
    buy=_s(taker_buy_base_volume); vol=_s(volume); return (2*buy-vol).cumsum()
def order_book_imbalance(bid_qty, ask_qty):
    b=_s(bid_qty); a=_s(ask_qty); return (b-a)/(b+a).replace(0,np.nan)
def microprice(bid_price, ask_price, bid_qty, ask_qty):
    bp,ap,bq,aq=map(_s,(bid_price,ask_price,bid_qty,ask_qty)); return (ap*bq+bp*aq)/(bq+aq).replace(0,np.nan)
def spread(bid_price, ask_price):
    bp,ap=map(_s,(bid_price,ask_price)); return pd.DataFrame({'spread_abs':ap-bp,'spread_rel':(ap-bp)/((ap+bp)/2).replace(0,np.nan)})
def ofi(bid_price,ask_price,bid_qty,ask_qty):
    bp,ap,bq,aq=map(_s,(bid_price,ask_price,bid_qty,ask_qty)); eb=pd.Series(0.,index=bp.index); ea=pd.Series(0.,index=bp.index); db=bp.diff(); da=ap.diff(); eb += np.where(db>0,bq,np.where(db<0,-bq,bq.diff().fillna(0))); ea += np.where(da<0,aq,np.where(da>0,-aq,aq.diff().fillna(0))); return eb-ea
def kyles_lambda(price, signed_volume, window=50):
    p=_s(price); v=_s(signed_volume); dp=p.diff(); cov=dp.rolling(window).cov(v); var=v.rolling(window).var(ddof=1); return cov/var.replace(0,np.nan)
def funding_roc(funding_rate, periods=1): return _s(funding_rate).pct_change(periods)
def basis(spot_price, futures_price): return (_s(futures_price)-_s(spot_price))/_s(spot_price).replace(0,np.nan)
def oi_price_quadrant(open_interest, close, window=5):
    oi_m=_s(open_interest).pct_change(window); p_m=_s(close).pct_change(window); out=pd.Series('neutral',index=oi_m.index,dtype='object'); out[(oi_m>0)&(p_m>0)]='long_build'; out[(oi_m>0)&(p_m<0)]='short_build'; out[(oi_m<0)&(p_m>0)]='short_cover'; out[(oi_m<0)&(p_m<0)]='long_unwind'; return out
def liquidation_cluster(long_notional, short_notional, window=20):
    return pd.DataFrame({'liq_long':_s(long_notional).rolling(window).sum(),'liq_short':_s(short_notional).rolling(window).sum()})
def hurst_rs(x, window=100):
    s=_s(x); out=pd.Series(np.nan,index=s.index)
    for i in range(window-1,len(s)):
        y=s.iloc[i-window+1:i+1].to_numpy(); d=np.diff(y); sd=d.std(ddof=1)
        if sd<=0: continue
        z=d-d.mean(); r=np.max(np.cumsum(z))-np.min(np.cumsum(z)); out.iloc[i]=np.log(r/sd)/np.log(window) if r>0 else np.nan
    return out
def rolling_skew(x, window=20): return _s(x).rolling(window).skew()
def rolling_kurtosis(x, window=20): return _s(x).rolling(window).kurt()


def chaikin_money_flow(high, low, close, volume, window=20):
    """Chaikin Money Flow (CMF): rolling money-flow volume / rolling volume."""
    h,l,c,v=map(_s,(high,low,close,volume))
    mfm=((c-l)-(h-c))/(h-l).replace(0,np.nan)
    return (mfm*v).rolling(window,min_periods=window).sum()/v.rolling(window,min_periods=window).sum().replace(0,np.nan)


def depth_within_bps(bid_prices, bid_qtys, ask_prices, ask_qtys, mid_price=None, bps=(1,5,10,25,50)):
    """Aggregate visible L2 depth within configurable basis-point bands."""
    def row(obj,i):
        if isinstance(obj,pd.Series): return obj.iloc[i]
        if isinstance(obj,pd.DataFrame): return obj.iloc[i].to_numpy()
        if isinstance(obj,np.ndarray) and obj.ndim>=2: return obj[i]
        if isinstance(obj,(list,tuple)) and len(obj)>i and isinstance(obj[i],(list,tuple,np.ndarray,pd.Series)): return obj[i]
        return obj
    lengths=[]
    for obj in (bid_prices,bid_qtys,ask_prices,ask_qtys,mid_price):
        if isinstance(obj,pd.Series): lengths.append(len(obj))
        elif isinstance(obj,np.ndarray) and obj.ndim>=2: lengths.append(obj.shape[0])
        elif isinstance(obj,(list,tuple)) and obj and not isinstance(obj[0],(int,float,np.number)): lengths.append(len(obj))
    n=max(lengths or [1])
    def scalar_mid(i):
        if mid_price is not None:
            x=row(mid_price,i); return float(np.asarray(x).reshape(-1)[0])
        bp=np.asarray(row(bid_prices,i),float).reshape(-1); ap=np.asarray(row(ask_prices,i),float).reshape(-1); return float((bp[0]+ap[0])/2)
    out={}
    for band in bps:
        bids=[]; asks=[]
        for i in range(n):
            m=scalar_mid(i); bp=np.asarray(row(bid_prices,i),float).reshape(-1); bq=np.asarray(row(bid_qtys,i),float).reshape(-1); ap=np.asarray(row(ask_prices,i),float).reshape(-1); aq=np.asarray(row(ask_qtys,i),float).reshape(-1)
            bids.append(float(bq[bp>=m*(1-band/10000)].sum()))
            asks.append(float(aq[ap<=m*(1+band/10000)].sum()))
        bd=np.asarray(bids); ad=np.asarray(asks); denom=bd+ad
        out[f'depth_bid_{band}bps']=bd; out[f'depth_ask_{band}bps']=ad
        out[f'depth_imbalance_{band}bps']=np.divide(bd-ad,denom,out=np.full(n,np.nan),where=denom!=0)
    return pd.DataFrame(out)


def trade_intensity(timestamps, decay_seconds=60.0):
    """Hawkes-style exponentially decayed trade/event intensity.

    Each event contributes one impulse and decays exponentially after its timestamp.
    This is a causal Hawkes-style feature, not a full maximum-likelihood Hawkes fit.
    """
    idx=pd.to_datetime(timestamps,utc=True)
    times=idx.astype('int64')/1e9
    out=np.zeros(len(idx),dtype=float); last=-np.inf; intensity=0.0
    for i,t in enumerate(times):
        if np.isfinite(last): intensity *= np.exp(-(t-last)/max(float(decay_seconds),1e-9))
        intensity += 1.0
        out[i]=intensity; last=t
    return pd.Series(out,index=getattr(timestamps,'index',None),name='trade_intensity')


def agg_trade_intensity(bar_index, trade_timestamps, decay_seconds=60.0, bar_duration=None):
    """Causal exponentially-decayed intensity from actual aggTrade event timestamps.

    Bar observations are treated as decision-at-close by default: when a regular bar index is supplied,
    the event horizon is shifted by the inferred bar duration so all trades inside a completed bar count.
    """
    bars=pd.to_datetime(bar_index,utc=True)
    if len(bars)>1:
        inferred=bar_duration or pd.Series(bars).diff().median()
    else:
        inferred=pd.Timedelta(0)
    horizons=bars + (pd.Timedelta(inferred) if inferred is not None else pd.Timedelta(0))
    events=pd.to_datetime(pd.Series(trade_timestamps),utc=True).dropna().sort_values()
    event_ns=events.astype('int64').to_numpy(dtype=np.int64)
    out=np.zeros(len(bars),dtype=float); decay=max(float(decay_seconds),1e-9)
    intensity=0.0; clock_ns=None; j=0
    for i,ts in enumerate(horizons):
        target=int(ts.value)
        while j < len(event_ns) and event_ns[j] <= target:
            ev=int(event_ns[j])
            if clock_ns is not None:
                intensity *= np.exp(-max(0.0,(ev-clock_ns)/1e9)/decay)
            intensity += 1.0
            clock_ns=ev; j += 1
        if clock_ns is not None and target>=clock_ns:
            intensity *= np.exp(-((target-clock_ns)/1e9)/decay)
            clock_ns=target
        out[i]=intensity
    return pd.Series(out,index=getattr(bar_index,'index',bar_index),name='trade_intensity')


def rolling_trade_intensity(timestamps, window=60, decay_seconds=60.0):
    """Windowed exponentially weighted trade/event intensity."""
    x=trade_intensity(timestamps,decay_seconds)
    return x.rolling(window,min_periods=1).mean()


def adf_statistic(x, window=100, max_lags=1):
    """Rolling Augmented Dickey-Fuller tau statistic without look-ahead."""
    s=_s(x); out=pd.Series(np.nan,index=s.index,name='adf_statistic'); lag=max(0,int(max_lags))
    for i in range(window-1,len(s)):
        y=s.iloc[i-window+1:i+1].to_numpy(float)
        if np.isnan(y).any() or len(y)<=lag+6: continue
        dy=np.diff(y)
        rows=[]; target=[]
        for t in range(lag,len(dy)):
            rows.append([1.0,y[t]]+[dy[t-k] for k in range(1,lag+1)])
            target.append(dy[t])
        X=np.asarray(rows,float); target=np.asarray(target,float)
        if len(target)<=X.shape[1]+1: continue
        try:
            beta=np.linalg.lstsq(X,target,rcond=None)[0]; resid=target-X@beta; dof=max(1,len(target)-X.shape[1]); sigma2=float(resid@resid/dof); cov=sigma2*np.linalg.pinv(X.T@X); se=float(np.sqrt(max(cov[1,1],0)))
            if se>0: out.iloc[i]=float(beta[1]/se)
        except np.linalg.LinAlgError: continue
    return out


def adf_reference_statistic(x, max_lags=1, regression='c'):
    """Reference ADF tau statistic using statsmodels for validation/debugging only."""
    try:
        from statsmodels.tsa.stattools import adfuller
    except ImportError as exc:
        raise ImportError("statsmodels is required for ADF reference validation") from exc
    arr=_s(x).dropna().to_numpy(float)
    if len(arr) < max(20, int(max_lags)+8):
        return float('nan')
    return float(adfuller(arr, maxlag=int(max_lags), regression=regression, autolag=None)[0])


def rolling_return_autocorrelation(close, lag=1, window=60):
    """Rolling autocorrelation of log returns at the requested lag."""
    r=log_returns(close)
    return r.rolling(window,min_periods=max(10,lag+5)).corr(r.shift(lag))
