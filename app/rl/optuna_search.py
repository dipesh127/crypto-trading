from __future__ import annotations
from pathlib import Path
import json
import numpy as np
import optuna
from .walkforward import purged_embargo_splits
from .training import train_ppo, evaluate_model
try:
    import mlflow
except ImportError:
    mlflow=None


def suggest_ppo(trial):
    return {
        'learning_rate':trial.suggest_float('learning_rate',1e-5,3e-4,log=True),
        'gamma':trial.suggest_float('gamma',0.95,0.999),
        'gae_lambda':trial.suggest_float('gae_lambda',0.90,0.99),
        'clip_range':trial.suggest_float('clip_range',0.10,0.30),
        'ent_coef':trial.suggest_float('ent_coef',1e-5,0.05,log=True),
        'lambda_cost':trial.suggest_float('lambda_cost',0.1,3.0,log=True),
        'lambda_dd':trial.suggest_float('lambda_dd',0.1,5.0,log=True),
        'policy_pi_arch':trial.suggest_categorical('policy_pi_arch',['128,64','256,128','256,128,64']),
        'policy_vf_arch':trial.suggest_categorical('policy_vf_arch',['128,64','256,128','256,128,64']),
    }

def make_study(direction='maximize',seed=7, storage=None, study_name=None):
    return optuna.create_study(direction=direction,sampler=optuna.samplers.TPESampler(seed=seed),storage=storage,study_name=study_name,load_if_exists=bool(storage and study_name))

def optimize_ppo(data, feature_cols, n_trials=20, n_splits=3, purge_bars=1, embargo_bars=1,
                 min_train_bars=500, min_validation_bars=100, timesteps_per_fold=10_000,
                 window=60, seed=7, output_dir='artifacts/optuna', storage=None, study_name='ppo_purged_cv'):
    """Optimize PPO on chronological purged/embargo CV; each trial trains/evaluates every fold."""
    splits=purged_embargo_splits(data,n_splits=n_splits,purge_bars=purge_bars,embargo_bars=embargo_bars,
                                  min_train_bars=min_train_bars,min_validation_bars=min_validation_bars)
    if not splits: raise ValueError('not enough data for requested purged/embargo CV')
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    study=make_study(seed=seed,storage=storage,study_name=study_name)

    def objective(trial):
        params=suggest_ppo(trial); params['net_arch']={'pi':[int(x) for x in params.pop('policy_pi_arch').split(',')],'vf':[int(x) for x in params.pop('policy_vf_arch').split(',')]}; scores=[]
        for fold,(train,val) in enumerate(splits):
            fold_dir=out/f'trial_{trial.number}'/f'fold_{fold}'
            _,path=train_ppo(train,feature_cols,total_timesteps=timesteps_per_fold,n_envs=1,window=window,
                             seed=seed+trial.number+fold,run_name=f'trial{trial.number}_fold{fold}',output_dir=fold_dir,
                             mlflow_run=False,**params)
            model_metrics=evaluate_model(path if path else None,val,feature_cols,window=window)
            score=float(model_metrics.get('Sharpe',np.nan))
            if not np.isfinite(score): score=-1e6
            scores.append(score); trial.report(float(np.mean(scores)),step=fold)
            if trial.should_prune(): raise optuna.TrialPruned()
        value=float(np.mean(scores)); trial.set_user_attr('fold_scores',scores); trial.set_user_attr('cv','purged_embargo'); trial.set_user_attr('fold_count',len(scores))
        if mlflow:
            with mlflow.start_run(run_name=f'optuna_trial_{trial.number}',nested=True):
                mlflow.log_params({k:v for k,v in params.items() if isinstance(v,(str,int,float,bool))})
                mlflow.log_metrics({'cv_mean_sharpe':value, **{f'fold_{i}_sharpe':float(v) for i,v in enumerate(scores)}})
                mlflow.set_tags({'optuna_trial':str(trial.number),'cv':'purged_embargo','purge_bars':str(purge_bars),'embargo_bars':str(embargo_bars)})
        return value

    study.optimize(objective,n_trials=n_trials)
    result={'best_value':study.best_value,'best_params':study.best_params,'n_trials':len(study.trials),'cv':'purged_embargo',
            'n_splits':len(splits),'purge_bars':purge_bars,'embargo_bars':embargo_bars}
    (out/'study_summary.json').write_text(json.dumps(result,indent=2,default=str))
    return study
