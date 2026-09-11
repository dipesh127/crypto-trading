import numpy as np, pandas as pd
from app.features import FeaturePipeline, btc_correlation, cross_sectional_features
from app.rl.walkforward import purged_embargo_splits
from app.sim.metrics import monte_carlo_trade_ci
from app.sim.engine import Simulator
from app.sim.fees import FeeSchedule
from app.sim.brackets import Bracket,BracketTable

def test_regime_and_cross_asset_features_are_integrated():
    n=140; idx=pd.date_range('2026-01-01',periods=n,freq='min',tz='UTC')
    def frame(mult=1):
        c=(100+np.arange(n)*0.1+np.sin(np.arange(n)/5))*mult
        return pd.DataFrame({'open':c,'high':c+1,'low':c-1,'close':c,'volume':100+np.arange(n)},index=idx)
    frames={'BTCUSDT':frame(),'ETHUSDT':frame(1.1),'SOLUSDT':frame(1.2)}
    p=FeaturePipeline(); out=p.compute_cross_asset(frames)
    assert 'regime_label' in out['ETHUSDT']
    assert 'btc_correlation' in out['ETHUSDT'] and 'btc_beta' in out['ETHUSDT']
    assert 'xs_return_rank' in out['ETHUSDT'] and 'xs_momentum_rank' in out['ETHUSDT']

def test_purged_embargo_has_no_boundary_overlap():
    d=pd.DataFrame({'x':np.arange(500)},index=pd.date_range('2026-01-01',periods=500,freq='min',tz='UTC'))
    splits=purged_embargo_splits(d,n_splits=3,purge_bars=5,embargo_bars=7,min_train_bars=200,min_validation_bars=50)
    assert splits
    for tr,val in splits:
        assert tr.index[-1] < val.index[0]
        assert (val.index[0]-tr.index[-1]).total_seconds()/60 >= 6

def test_monte_carlo_uses_dollar_pnl_additively():
    ci=monte_carlo_trade_ci([100,-50,25],n=100,seed=1,initial_cash=1000)
    assert np.isclose(ci['return_ci'][1],0.075)
    assert ci['initial_cash']==1000

def test_simulator_reports_holding_and_baselines():
    n=100; idx=pd.date_range('2026-01-01',periods=n,freq='min',tz='UTC'); c=100+np.sin(np.arange(n)/4)
    bars=pd.DataFrame({'open':c,'high':c+1,'low':c-1,'close':c,'volume':1000},index=idx)
    b={'BTCUSDT':BracketTable([Bracket(1,20,0,1e9,.004,0)])}
    sim=Simulator(FeeSchedule(0),b,initial_cash=10000)
    sig=pd.Series(0,index=idx); sig.iloc[10:30]=1; sig.iloc[30:40]=-1
    r=sim.run(bars,signals=sig,symbol='BTCUSDT')
    assert r['metrics']['average_holding_period_minutes']>0
    assert 'sma_crossover' in r['benchmarks'] and 'buy_and_hold_benchmark' in r['benchmarks']
