from __future__ import annotations
import json, subprocess
from pathlib import Path
import numpy as np
import pandas as pd
try: import mlflow
except ImportError: mlflow=None
try:
    from stable_baselines3 import PPO, SAC
    from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv
    from stable_baselines3.common.callbacks import BaseCallback
except ImportError:
    PPO=SAC=None; DummyVecEnv=SubprocVecEnv=None; BaseCallback=None
from .env import CryptoFuturesEnv, ContinuousCryptoFuturesEnv
from .policy import SharedTCNExtractor
from app.features.checkpoint import checkpoint_metadata, save_regime_state
from app.features.normalization import TrainOnlyScaler
from app.features.pipeline import FeaturePipeline


class MLflowTrainingCurveCallback(BaseCallback if BaseCallback else object):
    """Capture all numeric SB3 logger values over training for MLflow/CSV curves."""
    def __init__(self):
        if BaseCallback: super().__init__(verbose=0)
        self.rows=[]; self._last_logged_step=-1
    def _on_step(self):
        if not hasattr(self,'logger'): return True
        step=int(getattr(self,'num_timesteps',0))
        values=getattr(self.logger,'name_to_value',{}) or {}
        if step<=self._last_logged_step or not values: return True
        row={'step':step}
        for k,v in values.items():
            try:
                fv=float(v)
                if np.isfinite(fv): row[k]=fv
            except Exception: pass
        if len(row)>1:
            self.rows.append(row); self._last_logged_step=step
        return True

def _repo_root(): return Path(__file__).resolve().parents[2]

def git_commit():
    try: return subprocess.check_output(['git','rev-parse','HEAD'],cwd=_repo_root(),text=True).strip()
    except Exception: return 'unknown'

def git_dirty():
    try: return bool(subprocess.check_output(['git','status','--porcelain'],cwd=_repo_root(),text=True).strip())
    except Exception: return False

def build_envs(data, feature_cols, n_envs=4, continuous=False, **env_kwargs):
    cls=ContinuousCryptoFuturesEnv if continuous else CryptoFuturesEnv
    base_seed=env_kwargs.get('seed',7)
    def make(rank):
        def _f():
            local_kwargs=dict(env_kwargs); local_kwargs['seed']=base_seed+rank
            return cls(data,feature_cols=feature_cols,**local_kwargs)
        return _f
    makers=[make(i) for i in range(n_envs)]
    if n_envs==1: return DummyVecEnv(makers)
    return SubprocVecEnv(makers)

def model_metadata(data_window, feature_version, feature_columns, hyperparameters, backtest_metrics):
    feature_meta=checkpoint_metadata(feature_columns,Path('app/features'))
    return {'training_data_window':[str(data_window[0]),str(data_window[1])],'feature_set_version':feature_version,
            'feature_code_sha256':feature_meta['feature_code_sha256'],'schema_hash':feature_meta['schema_hash'],
            'feature_columns':list(feature_columns),'hyperparameters':hyperparameters,'backtest_metrics':backtest_metrics,
            'git_commit':git_commit(),'git_dirty':git_dirty()}

def _eval_model_object(model,data,feature_cols,window=60,continuous=False):
    env_cls=ContinuousCryptoFuturesEnv if continuous else CryptoFuturesEnv
    env=env_cls(data,feature_cols=feature_cols,window=window,randomize_costs=False)
    obs,reset_info=env.reset(); equities=[env.initial_cash]; times=[pd.Timestamp(reset_info.get('timestamp',data.index[min(window,len(data)-1)]))]; rewards=[]; done=False
    while not done:
        action,_=model.predict(obs,deterministic=True)
        obs,reward,terminated,truncated,info=env.step(action)
        rewards.append(float(reward)); equities.append(float(info['equity'])); times.append(pd.Timestamp(info.get('timestamp',data.index[min(env.i,len(data)-1)]))); done=terminated or truncated
    eq=pd.Series(equities,index=pd.to_datetime(times,utc=True),dtype=float)
    ret=eq.pct_change().replace([np.inf,-np.inf],np.nan).dropna()
    from app.sim.metrics import infer_periods_per_year; ppy=infer_periods_per_year(eq.index,default=None); sharpe=float(np.sqrt(ppy)*ret.mean()/ret.std(ddof=1)) if len(ret)>1 and ret.std(ddof=1)>0 else float('nan')
    dd=(eq/eq.cummax()-1).min()
    return {'total_return':float(eq.iloc[-1]/eq.iloc[0]-1),'Sharpe':sharpe,'max_drawdown':float(dd),
            'mean_reward':float(np.mean(rewards)) if rewards else 0.0,'final_equity':float(eq.iloc[-1]),'equity':eq}

def evaluate_model(path,data,feature_cols,window=60,algorithm='ppo'):
    if path is None: raise ValueError('model path required')
    cls=PPO if algorithm.lower()=='ppo' else SAC
    if cls is None: raise ImportError('stable-baselines3 is required')
    model=cls.load(str(path))
    return _eval_model_object(model,data,feature_cols,window,continuous=algorithm.lower()=='sac')

def _log_training_artifacts(run_name,out,model_path,metrics,params,metadata=None,curve_path=None):
    curve=out/f'{run_name}_equity.csv'; pd.DataFrame({'equity':metrics.pop('equity')}).to_csv(curve,index=False)
    summary=out/f'{run_name}_metrics.json'; summary.write_text(json.dumps(metrics,indent=2,default=str))
    if metadata:
        mp=out/f'{run_name}_metadata.json'; mp.write_text(json.dumps(metadata,indent=2,default=str))
    if mlflow:
        mlflow.log_params({k:v for k,v in params.items() if isinstance(v,(str,int,float,bool))})
        vals={k:float(v) for k,v in metrics.items() if isinstance(v,(int,float)) and np.isfinite(v)}
        if vals: mlflow.log_metrics(vals)
        mlflow.log_artifact(str(model_path),artifact_path='model')
        if curve_path is not None: mlflow.log_artifact(str(curve_path),artifact_path='training_curves')
        mlflow.set_tags({'git_sha':git_commit(),'git_dirty':str(git_dirty()).lower()})
        mlflow.log_artifact(str(curve),artifact_path='metrics')
        mlflow.log_artifact(str(summary),artifact_path='metrics')
        if metadata:
            mp=out/f'{run_name}_metadata.json'
            mlflow.log_artifact(str(mp),artifact_path='metadata')

def train_ppo(data,feature_cols,total_timesteps=100_000,n_envs=4,reward_mode='shaped',seed=7,run_name='ppo',output_dir='artifacts',mlflow_run=True,metadata=None,window=60,**kwargs):
    if PPO is None: raise ImportError("Install project dependencies to use PPO: pip install -e '.[dev]'")
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    train_params={k:kwargs.pop(k) for k in ['learning_rate','gamma','gae_lambda','clip_range','ent_coef'] if k in kwargs}
    env_kwargs={k:kwargs.pop(k) for k in ['lambda_cost','lambda_dd'] if k in kwargs}
    net_arch=kwargs.pop('net_arch', {'pi':[128,64],'vf':[128,64]})
    env=build_envs(data,feature_cols,n_envs=n_envs,continuous=False,reward_mode=reward_mode,randomize_costs=True,seed=seed,window=window,**env_kwargs,**kwargs)
    policy_kwargs={'features_extractor_class':SharedTCNExtractor,'features_extractor_kwargs':{'features_dim':256},'net_arch':net_arch,'ortho_init':True}
    model=PPO('MultiInputPolicy',env,learning_rate=train_params.get('learning_rate',3e-4),gamma=train_params.get('gamma',0.99),gae_lambda=train_params.get('gae_lambda',0.95),clip_range=train_params.get('clip_range',0.2),ent_coef=train_params.get('ent_coef',0.01),policy_kwargs=policy_kwargs,seed=seed,verbose=0)
    curve_cb=MLflowTrainingCurveCallback() if BaseCallback is not None else None
    path=out/f'{run_name}.zip'; regime_path=None; curve_path=None
    params={'algorithm':'PPO','reward_mode':reward_mode,'seed':seed,'n_envs':n_envs,'timesteps':total_timesteps,'net_arch':net_arch,**train_params,**env_kwargs}
    run_ctx=mlflow.start_run(run_name=run_name) if (mlflow and mlflow_run) else None
    try:
        def run_train(): model.learn(total_timesteps=total_timesteps,callback=curve_cb)
        run_train(); model.save(path)
        if {'open','high','low','close','volume'} <= set(data.columns):
            regime_path=out/f'{run_name}.regime.pkl'; regime_pipeline=FeaturePipeline(); regime_pipeline.fit_regime(data[['open','high','low','close','volume']]); save_regime_state(regime_path,regime_pipeline.regime_classifier); model.regime_model_path=str(regime_path)
        metrics=_eval_model_object(model,data,feature_cols,window=window,continuous=False)
        if curve_cb is not None and curve_cb.rows:
            curve_path=out/f'{run_name}_training_curves.csv'; pd.DataFrame(curve_cb.rows).to_csv(curve_path,index=False)
        metadata=metadata or {}
        metadata.setdefault('git_commit',git_commit()); metadata.setdefault('git_dirty',git_dirty())
        if mlflow and mlflow_run:
            _log_training_artifacts(run_name,out,path,metrics.copy(),params,metadata,curve_path)
    finally:
        if run_ctx is not None: mlflow.end_run()
    return model,path

def train_sac(data,feature_cols,total_timesteps=100_000,n_envs=4,seed=7,run_name='sac',output_dir='artifacts',mlflow_run=True,metadata=None,window=60,**kwargs):
    if SAC is None: raise ImportError("Install project dependencies to use SAC: pip install -e '.[dev]'")
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    reward_mode=kwargs.pop('reward_mode','shaped')
    train_params={k:kwargs.pop(k) for k in ['learning_rate','gamma'] if k in kwargs}
    env=build_envs(data,feature_cols,n_envs=n_envs,continuous=True,reward_mode=reward_mode,randomize_costs=True,seed=seed,window=window,**kwargs)
    policy_kwargs={'features_extractor_class':SharedTCNExtractor,'features_extractor_kwargs':{'features_dim':256},'net_arch':[256,128]}
    model=SAC('MultiInputPolicy',env,learning_rate=train_params.get('learning_rate',3e-4),gamma=train_params.get('gamma',0.99),ent_coef='auto',policy_kwargs=policy_kwargs,seed=seed,verbose=0)
    curve_cb=MLflowTrainingCurveCallback() if BaseCallback is not None else None
    path=out/f'{run_name}.zip'; params={'algorithm':'SAC','reward_mode':reward_mode,'seed':seed,'n_envs':n_envs,'timesteps':total_timesteps,'net_arch':policy_kwargs['net_arch'],**train_params}
    run_ctx=mlflow.start_run(run_name=run_name) if (mlflow and mlflow_run) else None
    try:
        model.learn(total_timesteps=total_timesteps,callback=curve_cb); model.save(path)
        metrics=_eval_model_object(model,data,feature_cols,window=window,continuous=True)
        curve_path=None
        if curve_cb is not None and curve_cb.rows:
            curve_path=out/f'{run_name}_training_curves.csv'; pd.DataFrame(curve_cb.rows).to_csv(curve_path,index=False)
        metadata=metadata or {}; metadata.setdefault('git_commit',git_commit()); metadata.setdefault('git_dirty',git_dirty())
        if mlflow and mlflow_run: _log_training_artifacts(run_name,out,path,metrics.copy(),params,metadata,curve_path)
    finally:
        if run_ctx is not None: mlflow.end_run()
    return model,path

