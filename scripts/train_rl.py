import argparse, json, asyncio
from pathlib import Path
import pandas as pd
from app.rl.training import train_ppo, train_sac, model_metadata, save_checkpoint_metadata
from app.features.normalization import TrainOnlyScaler

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--data',default='',help='CSV with UTC index/timestamp and features')
    ap.add_argument('--build-features-from-raw',action='store_true',help='Build the training frame from persisted raw Binance data')
    ap.add_argument('--symbol',default='BTCUSDT')
    ap.add_argument('--start',default='',help='UTC training start; required with --build-features-from-raw')
    ap.add_argument('--end',default='',help='UTC training end; required with --build-features-from-raw')
    ap.add_argument('--postgres-dsn',default='')
    ap.add_argument('--allow-incomplete-l2',action='store_true',help='Explicitly downgrade to non-L2 features when coverage is incomplete')
    ap.add_argument('--features',required=True,help='comma-separated feature columns')
    ap.add_argument('--algorithm',choices=['ppo','sac'],default='ppo')
    ap.add_argument('--timesteps',type=int,default=100000)
    ap.add_argument('--envs',type=int,default=4)
    ap.add_argument('--window',type=int,default=60)
    ap.add_argument('--output',default='artifacts')
    ap.add_argument('--oos-data',default='',help='Optional held-out CSV used only to calculate out-of-sample Sharpe metadata')
    ap.add_argument('--scaler',choices=['zscore','minmax'],default='zscore')
    args=ap.parse_args()
    if args.build_features_from_raw:
        if not args.start or not args.end: ap.error('--start and --end are required with --build-features-from-raw')
        from app.config import get_settings
        from app.features.raw_training import build_features_from_raw
        import asyncpg
        async def build():
            pool=await asyncpg.create_pool(args.postgres_dsn or get_settings().postgres_dsn)
            try:
                return await build_features_from_raw(pool,args.symbol,pd.Timestamp(args.start),pd.Timestamp(args.end),require_l2=not args.allow_incomplete_l2)
            finally: await pool.close()
        df=asyncio.run(build())
    else:
        if not args.data: ap.error('--data is required unless --build-features-from-raw is used')
        df=pd.read_csv(args.data,index_col=0,parse_dates=True).sort_index()
    cols=[x.strip() for x in args.features.split(',')]
    missing=set(cols)-set(df.columns)
    if missing: raise SystemExit(f'requested features are unavailable: {sorted(missing)}')
    scaler=TrainOnlyScaler(args.scaler); scaled=scaler.fit_transform(df[cols]); df.loc[:,cols]=scaled
    common={'window':args.window,'output_dir':args.output}
    if args.algorithm=='ppo': model,path=train_ppo(df,cols,total_timesteps=args.timesteps,n_envs=args.envs,**common)
    else: model,path=train_sac(df,cols,total_timesteps=args.timesteps,n_envs=args.envs,**common)
    backtest_metrics={}
    if args.oos_data:
        from app.rl.training import evaluate_model
        oos=pd.read_csv(args.oos_data,index_col=0,parse_dates=True).sort_index()
        oos.loc[:,cols]=scaler.transform(oos[cols])[cols]
        backtest_metrics=evaluate_model(path,oos,cols,window=args.window,algorithm=args.algorithm)
        backtest_metrics={k:v for k,v in backtest_metrics.items() if k!='equity'}
        backtest_metrics['oos_sharpe']=backtest_metrics.get('Sharpe')
    meta=model_metadata((df.index[0],df.index[-1]),'phase2-features-v1.3.0',cols,{'algorithm':args.algorithm,'timesteps':args.timesteps,'window':args.window,'scaler':args.scaler},backtest_metrics)
    meta['scaler']=scaler.state_dict()
    regime_path=Path(str(path).replace('.zip','.regime.pkl'))
    if regime_path.exists(): meta['regime_model']=str(regime_path)
    meta['oos_sharpe']=backtest_metrics.get('oos_sharpe')
    meta['training_source']='raw_binance_reconstruction' if args.build_features_from_raw else 'csv'
    meta['microstructure_complete']=bool(args.build_features_from_raw and not args.allow_incomplete_l2)
    if args.build_features_from_raw: meta['l2_coverage']=df.attrs.get('l2_coverage',{})
    save_checkpoint_metadata(Path(str(path)+'.metadata.json'),meta); print(path)
if __name__=='__main__': main()
