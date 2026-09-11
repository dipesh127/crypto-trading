import numpy as np, pandas as pd
from app.rl.env import CryptoFuturesEnv, ContinuousCryptoFuturesEnv
from app.rl.rewards import DifferentialSharpe

def data(n=150):
    idx=pd.date_range('2025-01-01',periods=n,freq='min',tz='UTC')
    close=100+np.cumsum(np.ones(n)*.01)
    return pd.DataFrame({'close':close,'f1':np.sin(np.arange(n)/5),'f2':np.cos(np.arange(n)/7)},index=idx)

def test_env_reset_step():
    e=CryptoFuturesEnv(data(),['f1','f2'],window=20)
    o,i=e.reset(seed=3); assert o['market'].shape==(20,2); assert o['account'].shape==(5,)
    o,r,t,tr,info=e.step(0); assert np.isfinite(r); assert 'equity' in info

def test_close_flat():
    e=CryptoFuturesEnv(data(),['f1'],window=20); e.reset(); e.step(0); e.step(3); assert e.position==0

def test_continuous_space():
    e=ContinuousCryptoFuturesEnv(data(),['f1'],window=20); e.reset(); e.step(np.array([.5])); assert e.position==.5

def test_differential_sharpe_finite():
    d=DifferentialSharpe(); vals=[d.update(x) for x in [.01,-.01,.02,-.005]]; assert all(np.isfinite(vals))
