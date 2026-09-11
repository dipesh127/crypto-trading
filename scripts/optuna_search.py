import argparse, json
import pandas as pd
from app.rl.optuna_search import optimize_ppo

def main():
    ap=argparse.ArgumentParser(description='PPO Optuna search with purged/embargo chronological CV')
    ap.add_argument('--data',required=True)
    ap.add_argument('--features',required=True)
    ap.add_argument('--trials',type=int,default=20)
    ap.add_argument('--folds',type=int,default=3)
    ap.add_argument('--purge',type=int,default=1)
    ap.add_argument('--embargo',type=int,default=1)
    ap.add_argument('--min-train',type=int,default=500)
    ap.add_argument('--min-validation',type=int,default=100)
    ap.add_argument('--timesteps-per-fold',type=int,default=10000)
    ap.add_argument('--window',type=int,default=60)
    ap.add_argument('--output',default='artifacts/optuna')
    ap.add_argument('--storage',default=None)
    ap.add_argument('--study-name',default='ppo_purged_cv')
    args=ap.parse_args()
    df=pd.read_csv(args.data,index_col=0,parse_dates=True).sort_index()
    cols=[x.strip() for x in args.features.split(',') if x.strip()]
    study=optimize_ppo(df,cols,n_trials=args.trials,n_splits=args.folds,purge_bars=args.purge,
        embargo_bars=args.embargo,min_train_bars=args.min_train,min_validation_bars=args.min_validation,
        timesteps_per_fold=args.timesteps_per_fold,window=args.window,output_dir=args.output,
        storage=args.storage,study_name=args.study_name)
    print(json.dumps({'best_value':study.best_value,'best_params':study.best_params},indent=2,default=str))

if __name__=='__main__': main()
