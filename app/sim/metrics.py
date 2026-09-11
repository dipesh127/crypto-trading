import numpy as np, pandas as pd
from scipy import stats

def _nw_se(x,lags=None):
    x=np.asarray(x,float); x=x[np.isfinite(x)]; n=len(x)
    if n<2:return np.nan
    lags=min(int(np.sqrt(n)) if lags is None else lags,n-1); gamma=np.var(x,ddof=0)
    for k in range(1,lags+1): gamma += 2*(1-k/(lags+1))*np.cov(x[k:],x[:-k],ddof=0)[0,1]
    return np.sqrt(max(gamma,0)/n)
def newey_west_ttest(x,null=0,lags=None):
    x=np.asarray(x,float); m=np.nanmean(x); se=_nw_se(x-m,lags); t=(m-null)/se if se and np.isfinite(se) else np.nan; df=max(1,len(x)-1)
    return {'mean':m,'se':se,'t':t,'pvalue':2*stats.t.sf(abs(t),df) if np.isfinite(t) else np.nan}
def infer_periods_per_year(index, default=None):
    idx=pd.to_datetime(index,utc=True,errors='coerce')
    if len(idx)<2 or getattr(idx,'isna',lambda:[])().any():
        if default is None: raise ValueError('periods_per_year is required when equity has no usable datetime index')
        return float(default)
    delta_ns=np.diff(idx.view('int64').astype(np.int64))
    delta_ns=delta_ns[delta_ns>0]
    if len(delta_ns)==0:
        if default is None: raise ValueError('cannot infer timeframe from equity index')
        return float(default)
    seconds=float(np.median(delta_ns))/1e9
    return float((365.25*24*3600)/seconds)

def performance(equity,trades=None,benchmark=None,periods_per_year=None):
    eq=pd.Series(equity).dropna();
    if len(eq)<2: return {'total_return':float('nan'),'CAGR':float('nan'),'Sharpe':float('nan'),'Sortino':float('nan'),'Calmar':float('nan'),'max_drawdown':float('nan')}
    ppy=infer_periods_per_year(eq.index,default=252 if periods_per_year is None and not isinstance(eq.index,pd.DatetimeIndex) else periods_per_year)
    r=eq.pct_change().fillna(0); years=((eq.index[-1]-eq.index[0]).total_seconds()/(365.25*24*3600)) if isinstance(eq.index,pd.DatetimeIndex) and len(eq.index)>1 else len(r)/ppy; total=eq.iloc[-1]/eq.iloc[0]-1; cagr=(1+total)**(1/years)-1 if years>0 else np.nan
    dd=eq/eq.cummax()-1; sharpe=np.sqrt(ppy)*r.mean()/r.std(ddof=1) if r.std(ddof=1)>0 else np.nan; downside=r[r<0].std(ddof=1); sortino=np.sqrt(ppy)*r.mean()/downside if downside and downside>0 else np.nan; calmar=cagr/abs(dd.min()) if dd.min()<0 else np.nan
    out={'total_return':total,'CAGR':cagr,'Sharpe':sharpe,'Sortino':sortino,'Calmar':calmar,'max_drawdown':dd.min(),'periods_per_year':ppy}
    if trades is not None and len(trades):
        p=np.asarray([t for t in trades if t>0]); l=np.asarray([t for t in trades if t<0]); out.update(win_rate=len(p)/len(trades),average_win=p.mean() if len(p) else 0,average_loss=l.mean() if len(l) else 0,profit_factor=p.sum()/abs(l.sum()) if len(l) else np.inf,expectancy=np.mean(trades))
    if benchmark is not None: out['benchmark_total_return']=pd.Series(benchmark).iloc[-1]/pd.Series(benchmark).iloc[0]-1
    return out

def monte_carlo_trade_ci(trades,n=5000,seed=7,initial_cash=10_000.0,timestamps=None,periods_per_year=None):
    """Bootstrap dollar PnL trades using additive cash/equity. Annualizes Sharpe only when actual timing is available."""
    t=np.asarray(trades,float); t=t[np.isfinite(t)]
    if len(t)==0: raise ValueError('trades cannot be empty')
    if initial_cash<=0: raise ValueError('initial_cash must be positive')
    ppy=periods_per_year
    if ppy is None and timestamps is not None and len(timestamps)>1:
        idx=pd.to_datetime(timestamps,utc=True,errors='coerce'); idx=idx[~idx.isna()]
        if len(idx)>1:
            delta=np.diff(idx.view('int64').astype('int64')); delta=delta[delta>0]
            if len(delta): ppy=(365.25*24*3600)/(float(np.median(delta))/1e9)
    scale=float(np.sqrt(ppy)) if ppy and ppy>0 else None
    rng=np.random.default_rng(seed); returns=[]; sharpes=[]
    for _ in range(int(n)):
        s=rng.choice(t,size=len(t),replace=True); eq=np.concatenate(([initial_cash],initial_cash+np.cumsum(s)))
        r=pd.Series(eq).pct_change().dropna().to_numpy(); returns.append(eq[-1]/initial_cash-1)
        sd=np.std(r,ddof=1); sharpes.append(float(np.mean(r)/sd*(scale if scale else 1.0)) if sd>0 else np.nan)
    valid=np.asarray([x for x in sharpes if np.isfinite(x)],dtype=float)
    return {'return_ci':np.percentile(returns,[2.5,50,97.5]).tolist(),'sharpe_ci':np.percentile(valid,[2.5,50,97.5]).tolist() if len(valid) else [np.nan]*3,'initial_cash':float(initial_cash),'trades':int(len(t)),'periods_per_year':ppy,'annualized':bool(scale)}

def significance(strategy,benchmark=None):
    out={'vs_zero':newey_west_ttest(strategy)}
    if benchmark is not None: out['vs_benchmark']=newey_west_ttest(np.asarray(strategy)-np.asarray(benchmark))
    return out
