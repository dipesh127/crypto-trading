import numpy as np, pandas as pd
from app.features import *

def series(n=160):
    x=np.arange(1,n+1,dtype=float); return x

def ohlcv(n=160):
    c=series(n)+0.25; h=c+1; l=c-1; o=c-0.1; v=np.arange(1,n+1,dtype=float)*10
    return pd.DataFrame({'open':o,'high':h,'low':l,'close':c,'volume':v})

def test_log_returns():
    assert np.isclose(log_returns(pd.Series([100.,110.])).iloc[1],np.log(1.1))

def test_rolling_vol_zscore_minmax():
    x=pd.Series([1.,2.,3.,4.,5.]); assert np.isclose(rolling_volatility(x,3).iloc[-1],np.std(np.diff(np.log(x))[-3:],ddof=1)); assert np.isclose(zscore(x,3).iloc[-1],1.); assert np.isclose(minmax(x,3).iloc[-1],1.)

def test_sma_ema():
    x=pd.Series([1.,2.,3.,4.,5.]); assert np.isclose(sma(x,3).iloc[-1],4.); assert np.isclose(ema(x,3).iloc[2],2.25)

def test_macd():
    x=pd.Series(np.arange(1,50,dtype=float)); m=macd(x); assert list(m.columns)==['macd','signal','histogram']; assert np.isclose((m.macd-m.signal-m.histogram).dropna().iloc[-1],0)

def test_adx_constant_uptrend():
    c=pd.Series(np.arange(1,80,dtype=float)); h=c+1; l=c-1; a=adx(h,l,c,14); assert a.plus_di.dropna().iloc[-1]>a.minus_di.dropna().iloc[-1]

def test_ichimoku_constant():
    h=pd.Series([11.]*80); l=pd.Series([9.]*80); c=pd.Series([10.]*80); i=ichimoku(h,l,c); assert np.isclose(i.iloc[-1].dropna().astype(float),10).all()

def test_rsi_wilder():
    r=rsi(pd.Series(np.arange(1,60,dtype=float)),14); assert np.isclose(r.dropna().iloc[-1],100.)

def test_stochastic_cci_roc_willr():
    d=ohlcv(); st=stochastic(d.high,d.low,d.close,14); assert 0<=st.stoch_k.dropna().iloc[-1]<=100; assert np.isclose(roc(pd.Series([100.,110.]),1).iloc[-1],10.); assert np.isclose(williams_r(d.high,d.low,d.close,14).dropna().iloc[-1],-6.666666666666667,atol=1e-10); assert cci(d.high,d.low,d.close,20).notna().any()

def test_bollinger_atr_keltner():
    d=ohlcv(); b=bollinger(d.close,20,2); assert np.isclose(b.bb_mid.dropna().iloc[-1],d.close.iloc[-20:].mean()); assert np.isclose(atr(pd.Series([11.]*30),pd.Series([9.]*30),pd.Series([10.]*30),14).dropna().iloc[-1],2); k=keltner(d.high,d.low,d.close); assert {'kc_mid','kc_upper','kc_lower'}==set(k.columns)

def test_obv_vwap_cvd():
    c=pd.Series([1.,2.,1.]); v=pd.Series([10.,20.,30.]); assert np.isclose(obv(c,v).iloc[-1],-10); assert np.isclose(vwap(c+1,c-1,c,v).iloc[-1],(1*10+2*20+1*30)/60); assert np.isclose(cvd(pd.Series([7.,5.]),pd.Series([10.,10.])).iloc[-1],4.)

def test_microstructure():
    bp=pd.Series([100.,101.]); ap=pd.Series([101.,102.]); bq=pd.Series([5.,5.]); aq=pd.Series([5.,5.]); assert np.isclose(order_book_imbalance(pd.Series([3]),pd.Series([1])).iloc[0],.5); assert np.isclose(microprice(pd.Series([99]),pd.Series([101]),pd.Series([3]),pd.Series([1])).iloc[0],100.5); assert np.isclose(spread(bp,ap).spread_abs.iloc[0],1); assert np.isclose(ofi(bp,ap,bq,aq).iloc[1],10)

def test_kyle_funding_basis_oi_liquidations():
    p=pd.Series(np.arange(100.,140.)); v=pd.Series(np.arange(1.,41.)); assert kyles_lambda(p,v,10).notna().any(); f=pd.Series([.01,.02]); assert np.isclose(funding_roc(f).iloc[-1],1.); assert np.isclose(basis(pd.Series([100.]),pd.Series([102.])).iloc[0],.02); q=oi_price_quadrant(pd.Series([100.,110.]),pd.Series([100.,110.]),1); assert q.iloc[-1]=='long_build'; lc=liquidation_cluster(pd.Series([1.,2.]),pd.Series([3.,4.]),2); assert lc.liq_long.iloc[-1]==3 and lc.liq_short.iloc[-1]==7

def test_hurst_skew_kurtosis():
    x=pd.Series(np.arange(1,140,dtype=float)+0.1*np.sin(np.arange(1,140))); assert hurst_rs(x,50).notna().any(); r=log_returns(x); assert rolling_skew(r,20).notna().any(); assert rolling_kurtosis(r,20).notna().any()

def test_normalizer_train_only():
    s=TrainOnlyScaler('zscore').fit(pd.DataFrame({'x':[1.,2.,3.]})); assert np.isclose(s.transform(pd.DataFrame({'x':[4.]})).iloc[0,0],2.); state=s.state_dict(); assert TrainOnlyScaler.from_state_dict(state).transform(pd.DataFrame({'x':[4.]})).iloc[0,0]==2.

def test_regime_classifier():
    x=pd.DataFrame({'volatility':[.1,.2,.1,.3,.4,.3,.5,.4], 'trend_strength':[.1,.2,.1,.3,.4,.3,.5,.4], 'volume_z':[0,1,0,1,2,2,3,3], 'trend_return':[-.3,-.2,-.1,.1,.2,.3,.4,.5]}); labels=MarketRegimeClassifier(2).fit_predict(x); assert labels.notna().all()

def test_pipeline_and_mtf():
    d=ohlcv(); d['taker_buy_base_volume']=d.volume*.6; d['bid_price']=d.close-.1; d['ask_price']=d.close+.1; d['bid_qty']=10.; d['ask_qty']=8.; d['funding_rate']=.0001; d['open_interest']=1000+np.arange(len(d)); d['liq_long']=1.; d['liq_short']=2.; out=FeaturePipeline().compute(d); assert 'ichimoku_span_a' in out and 'obi' in out and 'oi_price_quadrant' in out; mtf=FeaturePipeline().compute_multitimeframe({'1m':d,'5m':d,'15m':d,'1h':d}); assert 'rsi_1m' in mtf and 'rsi_1h' in mtf
