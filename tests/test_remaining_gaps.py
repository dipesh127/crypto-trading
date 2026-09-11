import numpy as np, pandas as pd
from app.features.indicators import chaikin_money_flow, depth_within_bps, adf_statistic, rolling_return_autocorrelation, trade_intensity
from app.features.pipeline import FeaturePipeline
from app.rl.ensemble import EnsemblePolicy, EnsembleMember
from app.risk.sharpe_decay import sharpe_decay
from app.sim.execution import AlmgrenChrissExecution

class Dummy:
    def __init__(self,a): self.a=a
    def predict(self,obs,deterministic=True): return self.a,None

def test_new_feature_families():
    n=140; c=pd.Series(100+np.sin(np.arange(n)/5)+np.arange(n)*.1); h=c+1;l=c-1;v=pd.Series(100+np.arange(n))
    assert chaikin_money_flow(h,l,c,v,20).notna().any()
    dep=depth_within_bps([99],[10],[101],[8],mid_price=100); assert dep.iloc[0]['depth_bid_1bps']==0; assert 'depth_imbalance_5bps' in dep
    assert adf_statistic(c,50).notna().any(); assert rolling_return_autocorrelation(c,1,30).notna().any(); assert trade_intensity(pd.date_range('2026-01-01',periods=10,freq='s')).iloc[-1]>1

def test_pipeline_adds_required_features():
    n=140; idx=pd.date_range('2026-01-01',periods=n,freq='min',tz='UTC'); c=pd.Series(100+np.arange(n)*.1,index=idx)
    d=pd.DataFrame({'open':c,'high':c+1,'low':c-1,'close':c,'volume':1000.,'bid_price':c-.1,'ask_price':c+.1,'bid_qty':10.,'ask_qty':8.},index=idx)
    out=FeaturePipeline().compute(d); assert {'cmf','adf_statistic','return_autocorrelation_1','depth_bid_5bps'} <= set(out.columns)

def test_l2_depth_columns_work_in_pipeline():
    n=140; idx=pd.date_range('2026-01-01',periods=n,freq='min',tz='UTC'); c=pd.Series(100+np.arange(n)*.1,index=idx)
    d=pd.DataFrame({'open':c,'high':c+1,'low':c-1,'close':c,'volume':1000.,'bid_prices':[[99.9,99.8,99.5]]*n,'bid_qtys':[[10,20,30]]*n,'ask_prices':[[100.1,100.2,100.5]]*n,'ask_qtys':[[8,16,24]]*n},index=idx)
    out=FeaturePipeline().compute(d); assert out['depth_bid_25bps'].notna().any()

def test_ensemble_weighted_vote():
    p=EnsemblePolicy([EnsembleMember(Dummy(1),2),EnsembleMember(Dummy(0),1)]); a,info=p.predict({}); assert a==1 and info['scores'][1]>info['scores'][0]

def test_sharpe_decay():
    assert sharpe_decay(0.6,1.0,0.5).breached is False; assert sharpe_decay(0.49,1.0,0.5).breached is True

def test_ac_schedule_conserves_quantity():
    ac=AlmgrenChrissExecution(100,steps=10); _,s=ac.schedule(); assert np.isclose(sum(s),100)
