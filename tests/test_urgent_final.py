import json, subprocess, sys, numpy as np, pandas as pd
from app.rl.env import account_observation
from app.features.microstructure import replay_book, aggregate_trades, merge_microstructure

def test_account_observation_matches_training_semantics():
    x=account_observation(0.01,100000,100,5,10000,time_in_position_seconds=180,window_bars=60,bar_seconds=60)
    assert x.shape==(5,)
    assert np.isclose(x[0],0.02)
    assert np.isclose(x[1],0.01)
    assert np.isclose(x[2],5.0)
    assert np.isclose(x[3],50.0)
    assert np.isclose(x[4],0.05)

def test_replay_book_uses_only_prior_snapshot():
    idx=pd.Timestamp('2026-01-01T00:00:00Z')
    snaps=pd.DataFrame([{'snapshot_time':idx,'last_update_id':1,'bids':[[100,2]],'asks':[[101,3]]}])
    updates=pd.DataFrame([{'event_time':idx+pd.Timedelta(seconds=2),'first_update_id':2,'final_update_id':2,'bids':[[100,1]],'asks':[[101,4]]}])
    out=replay_book(snaps,updates,idx,idx+pd.Timedelta(seconds=10))
    assert len(out)==1 and out.iloc[0]['bid_qty']==1

def test_microstructure_aggregates_trades_and_intensity():
    t=pd.DataFrame([
      {'trade_time':'2026-01-01T00:00:00Z','agg_id':1,'price':100,'quantity':2,'buyer_is_maker':False},
      {'trade_time':'2026-01-01T00:00:30Z','agg_id':2,'price':101,'quantity':1,'buyer_is_maker':True}])
    t['trade_time']=pd.to_datetime(t['trade_time'],utc=True)
    out=aggregate_trades(t)
    assert int(out.iloc[0]['trade_count'])==2 and np.isclose(out.iloc[0]['signed_volume'],1)

def test_explain_cli_accepts_json_help():
    r=subprocess.run([sys.executable,'scripts/verify_dashboard_indexes.py','--help'],cwd='.',capture_output=True,text=True,env={**__import__('os').environ,'PYTHONPATH':'.'})
    assert r.returncode==0 and '--json' in r.stdout and '--max-ms' in r.stdout
