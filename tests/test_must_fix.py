from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from app.features.pipeline import FeaturePipeline
from app.features.indicators import agg_trade_intensity
from app.features.checkpoint import save_regime_state, load_regime_state
from app.rl.env import CryptoFuturesEnv
from app.rl.optuna_search import suggest_ppo
from app.risk.manager import RiskManager, RiskConfig
from app.sim.execution import ExecutionModel
from app.sim.orders import Order, OrderType
from app.sim.fees import FeeSchedule
from app.sim.brackets import Bracket, BracketTable
from app.sim.engine import Simulator
from app.sim.metrics import performance


def ohlcv(n=180, freq='min'):
    idx=pd.date_range('2026-01-01',periods=n,freq=freq,tz='UTC')
    c=100+np.sin(np.arange(n)/8)+np.arange(n)*0.03
    return pd.DataFrame({'open':c,'high':c+1,'low':c-1,'close':c,'volume':1000+np.arange(n)},index=idx)


def test_simple_return_explicit_and_regime_no_live_refit(tmp_path):
    d=ohlcv()
    p=FeaturePipeline(); out=p.compute(d)
    assert 'simple_return' in out.columns
    before=repr(p.regime_classifier.model.cluster_centers_)
    model_path=tmp_path/'regime.pkl'; save_regime_state(model_path,p.regime_classifier)
    q=FeaturePipeline().load_regime(model_path)
    q.compute(d,fit_regime=False)
    assert repr(q.regime_classifier.model.cluster_centers_)==before
    r=FeaturePipeline()
    with pytest.raises(RuntimeError): r.compute(d,fit_regime=False)


def test_aggtrade_intensity_preserves_event_multiplicity():
    bars=pd.date_range('2026-01-01',periods=3,freq='min',tz='UTC')
    events=[bars[0]+pd.Timedelta(seconds=1),bars[0]+pd.Timedelta(seconds=2),bars[1]+pd.Timedelta(seconds=1)]
    x=agg_trade_intensity(bars,events,decay_seconds=60)
    assert x.iloc[0]>0
    assert x.iloc[1]>0
    assert x.iloc[2]>0


def test_optuna_space_contains_reward_weights_and_network_architecture():
    class Trial:
        def suggest_float(self,n,*a,**k): return 1.0
        def suggest_categorical(self,n,choices): return choices[0]
    p=suggest_ppo(Trial())
    assert 'lambda_cost' in p and 'lambda_dd' in p and 'policy_pi_arch' in p and 'policy_vf_arch' in p


def test_lambda_weights_reach_environment():
    d=ohlcv(90)
    cols=['simple_return']
    f=FeaturePipeline().compute(d)
    env=CryptoFuturesEnv(pd.concat([d[['close']],f],axis=1),feature_cols=cols,window=10,lambda_cost=2.3,lambda_dd=4.2)
    assert env.lambda_cost==2.3 and env.lambda_dd==4.2


def test_benchmark_newey_west_significance_and_ac_slicing():
    n=30; idx=pd.date_range('2026-01-01',periods=n,freq='min',tz='UTC'); c=np.linspace(100,101,n)
    bars=pd.DataFrame({'open':c,'high':c+1,'low':c-1,'close':c,'volume':1000},index=idx)
    bracket={'BTCUSDT':BracketTable([Bracket(1,20,0,1e9,.004,0)])}
    sim=Simulator(FeeSchedule(0),bracket,execution_model='almgren_chriss',ac_config={'risk_aversion':1e-6,'volatility':.02,'temporary_impact':.01,'steps':5})
    result=sim.run(bars,orders=[Order(1,1,50,OrderType.MARKET)],symbol='BTCUSDT')
    assert 'vs_benchmark' in result['metrics']['significance']
    assert len(result['fills'])>=2
    assert np.isclose(sum(f.qty for f in result['fills']),50)


def test_actual_timeframe_annualization():
    minute=ohlcv(5000,'min'); daily=ohlcv(100,'D')
    pm=performance(pd.Series(np.linspace(100,110,len(minute)),index=minute.index))
    pdaily=performance(pd.Series(np.linspace(100,110,len(daily)),index=daily.index))
    assert pm['periods_per_year']>500000 and pdaily['periods_per_year']<400


def test_sharpe_pause_requires_n_completed_days():
    cfg=RiskConfig(sharpe_floor=0.5,sharpe_decay_consecutive_days=3,daily_sharpe_window_days=2,rolling_sharpe_window=2)
    r=RiskManager(cfg)
    start=pd.Timestamp('2026-01-01',tz='UTC')
    for day in range(3):
        t=start+pd.Timedelta(days=day)
        r.observe(equity=1000,return_t=-0.01,now=t+pd.Timedelta(minutes=1),ws_connected=True)
        r.observe(equity=990,return_t=-0.01,now=t+pd.Timedelta(hours=23),ws_connected=True)
    # Finalize day 3 by entering day 4.
    reasons=r.observe(equity=980,return_t=-0.01,now=start+pd.Timedelta(days=3),ws_connected=True)
    assert 'rolling_sharpe_decay' not in reasons
    assert r.sharpe_floor_streak<=3

def test_train_ppo_forwards_reward_weights_and_architecture(monkeypatch, tmp_path):
    import app.rl.training as training
    captured={}
    class FakeEnv:
        pass
    class FakeModel:
        def __init__(self,*args,**kwargs): captured['policy_kwargs']=kwargs['policy_kwargs']; self.path=None
        def learn(self,*args,**kwargs): pass
        def save(self,path): self.path=str(path); Path(path).write_text('fake')
        def predict(self,obs,deterministic=True): return 2,None
    monkeypatch.setattr(training,'PPO',FakeModel)
    monkeypatch.setattr(training,'build_envs',lambda *a,**kw: captured.update({'env_kwargs':kw}) or FakeEnv())
    monkeypatch.setattr(training,'_eval_model_object',lambda *a,**kw: {'total_return':0.0,'Sharpe':0.0,'max_drawdown':0.0,'mean_reward':0.0,'final_equity':10000.0,'equity':pd.Series([10000,10001],index=pd.date_range('2026-01-01',periods=2,tz='UTC'))})
    training.train_ppo(ohlcv(40),['simple_return'],total_timesteps=2,n_envs=1,window=5,output_dir=tmp_path,mlflow_run=False,lambda_cost=2.2,lambda_dd=3.3,net_arch={'pi':[256,128],'vf':[128,64]})
    assert captured['env_kwargs']['lambda_cost']==2.2 and captured['env_kwargs']['lambda_dd']==3.3
    assert captured['policy_kwargs']['net_arch']=={'pi':[256,128],'vf':[128,64]}
