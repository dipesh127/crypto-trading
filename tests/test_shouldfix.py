import numpy as np
import pandas as pd
from app.features.indicators import adf_statistic, adf_reference_statistic, ichimoku, ichimoku_representations
from app.risk.drift import per_feature_drift
from app.sim.brackets import Bracket, BracketTable
from app.sim.liquidation import isolated_liquidation_price

def test_adf_matches_statsmodels_reference():
    rng=np.random.default_rng(7); x=pd.Series(np.cumsum(rng.normal(0,1,250)))
    ours=adf_statistic(x,window=120,max_lags=1).iloc[-1]; ref=adf_reference_statistic(x.iloc[-120:],max_lags=1)
    assert np.isfinite(ours) and np.isfinite(ref)
    assert abs(ours-ref)<1e-8

def test_ichimoku_representations_are_explicit():
    x=pd.Series(np.arange(100,dtype=float)); h=x+1; l=x-1
    c=ichimoku(h,l,x,representation='causal'); t=ichimoku(h,l,x,representation='traditional')
    assert np.isclose(c.iloc[54].ichimoku_span_a,t.iloc[80].ichimoku_span_a, equal_nan=False)
    both=ichimoku_representations(h,l,x)
    assert {'ichimoku_span_a_causal','ichimoku_span_a_traditional'}<=set(both.columns)

def test_per_feature_drift_detects_only_changed_feature():
    rng=np.random.default_rng(4); train=pd.DataFrame({'stable':rng.normal(size=2000),'drift':rng.normal(size=2000)})
    live=pd.DataFrame({'stable':rng.normal(size=2000),'drift':rng.normal(loc=3,size=2000)})
    d=per_feature_drift(train,live)
    assert d['drift']['psi']>d['stable']['psi']
    assert d['drift']['kl']>d['stable']['kl']

def test_liquidation_reference_vectors_and_fee_buffer():
    b=BracketTable([Bracket(1,20,0,50000,.004,0),Bracket(2,10,50000,100000,.005,50),Bracket(3,5,100000,500000,.01,550)])
    assert np.isclose(isolated_liquidation_price(100,1,10,b,1),90.3614457831,rtol=0,atol=1e-9)
    assert np.isclose(isolated_liquidation_price(100,1,10,b,-1),109.56175298804781,rtol=0,atol=1e-9)
    p0=isolated_liquidation_price(100,1000,10000,b,1); p1=isolated_liquidation_price(100,1000,10000,b,1,fee_buffer=100)
    assert p1>p0
    # bracket-2 reference, not bracket-1 approximation
    p=isolated_liquidation_price(100,750,10000,b,1)
    assert 100000/1.0*0+50000 <= p*750 < 100000

import asyncio
from unittest.mock import AsyncMock
from app.rl.realtime import BinanceFeatureStore
from app.sim.execution import AlmgrenChrissExecution
from app.sim.metrics import monte_carlo_trade_ci


def test_mc_trade_ci_uses_timestamp_annualization_when_available():
    ts=pd.date_range('2026-01-01',periods=20,freq='1h',tz='UTC')
    out=monte_carlo_trade_ci([1.0]*20,n=10,seed=3,initial_cash=1000,timestamps=ts)
    assert out['annualized'] is True
    assert out['periods_per_year'] > 8000


def test_ac_uses_linear_trade_rate_components():
    ac=AlmgrenChrissExecution(total_qty=100,temporary_impact=0.02,permanent_impact=0.01,steps=10)
    t1,p1=ac.impact_components(100,1,1,1000)
    t2,p2=ac.impact_components(100,1,2,1000)
    assert np.isclose(t2,2*t1)
    assert np.isclose(p2,2*p1)


def test_feature_store_has_no_normal_market_rest_polling(monkeypatch):
    class FakeRedis:
        async def xrevrange(self,*a,**k): return []
        async def get(self,*a,**k): return None
    class FakePool:
        def acquire(self):
            raise AssertionError('db fallback should not be needed for this test')
    class FakeRest:
        pass
    pipe=__import__('app.features.pipeline',fromlist=['FeaturePipeline']).FeaturePipeline(); pipe.regime_fitted=True
    monkeypatch.setattr(pipe,'compute_multitimeframe',lambda frames,**kw: pd.DataFrame(index=pd.date_range('2026-01-01',periods=2,tz='UTC')))
    with __import__('pytest').raises(RuntimeError):
        BinanceFeatureStore(FakeRest(),'BTCUSDT',redis=FakeRedis(),pipeline=pipe,scaler_state=None,require_scaler=True)
