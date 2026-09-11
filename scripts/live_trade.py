#!/usr/bin/env python3
import argparse, asyncio, json, logging, time
from decimal import Decimal
from pathlib import Path
import asyncpg
from app.config import get_settings
from app.binance import BinanceREST
from app.live import BinanceLiveExecutionAdapter
from app.paper import PaperTradingEngine
from app.reconciliation import Reconciler
from app.db import ExecutionDBLogger
from app.rl.live_policy import TrainedPolicy
from app.rl.realtime import BinanceFeatureStore
from redis import asyncio as redis_asyncio
from app.risk.manager import RiskManager, RiskConfig
from app.alerts import AlertDispatcher
from app.monitoring import observe_inference, observe_rest_error, observe_risk_veto, observe_fill, observe_order, set_account_telemetry
from app.golive import authorize_live, GoLiveEvidence
from app.governance import CapitalRampController, LiveGovernanceSupervisor, GovernanceConfig, ChallengerPipeline

async def main():
    p=argparse.ArgumentParser(description="Phase 8 live trading. Requires successful fail-closed preflight.")
    p.add_argument('--model',required=True)
    p.add_argument('--ensemble-models',default='',help='Comma-separated checkpoints for weighted voting ensemble'); p.add_argument('--metadata',required=True); p.add_argument('--evidence',required=True)
    p.add_argument('--symbol',default='BTCUSDT'); p.add_argument('--quantity',required=True); p.add_argument('--interval',type=float,default=60.0)
    p.add_argument('--reconcile-seconds',type=float,default=30.0); p.add_argument('--max-leverage',type=float,default=3.0)
    p.add_argument('--approved-capital',type=float,required=True, help='Maximum capital approved for this live deployment')
    p.add_argument('--ramp-stage',type=int,default=0, help='0=10%%, 1=25%%, 2=50%%, 3=75%%, 4=100%%')
    p.add_argument('--ramp-reviewer',required=True)
    p.add_argument('--retrain-command',default='', help='Offline retraining command; creates challenger only, never promotes')
    p.add_argument('--training-feature-values',default='', help='CSV/text file of training feature samples for drift detection')
    a=p.parse_args(); s=get_settings()
    auth=authorize_live(a.evidence)
    if s.app_env.lower() != 'live': raise SystemExit('Refusing live execution unless APP_ENV=live')
    if not auth['authorized']: raise SystemExit('Live authorization failed')
    if not s.binance_api_key or not s.binance_api_secret: raise SystemExit('Live API credentials are required')
    meta=json.loads(Path(a.metadata).read_text()); feature_columns=meta['feature_columns']; window=int(meta.get('observation_window',60)); regime_model=meta.get('regime_model')
    if not regime_model or not Path(regime_model).exists(): raise SystemExit('Persisted training regime model is required; live/paper inference will not fit a regime model')
    evidence=GoLiveEvidence.load(a.evidence)
    ramp=CapitalRampController()
    if ramp.state.approved_capital <= 0:
        if a.ramp_stage != 0: raise SystemExit('First live deployment must start at ramp stage 0 (10%).')
        ramp.activate_initial(approved_capital=a.approved_capital, reviewer=a.ramp_reviewer, human_approved=True)
    else:
        if abs(ramp.state.approved_capital-a.approved_capital)>1e-9: raise SystemExit('approved capital differs from persisted capital ramp')
        ramp.validate_runtime_stage(a.ramp_stage)
    logging.basicConfig(level=s.log_level)
    risk=RiskManager(RiskConfig(max_leverage=a.max_leverage, flatten_on_connectivity_failure=True))
    latest_equity={"value": None}
    pool=await asyncpg.create_pool(s.postgres_dsn)
    db=ExecutionDBLogger(pool,mode='LIVE')
    db.set_alert_dispatcher(AlertDispatcher.from_env())
    redis=redis_asyncio.from_url(s.redis_url,decode_responses=True)
    rest=BinanceREST(s.binance_rest_base_url,s.binance_api_key,s.binance_api_secret,s.binance_recv_window_ms,s.binance_ws_base_url,raw_requests_per_minute=s.binance_raw_requests_per_minute,order_requests_per_minute=s.binance_order_requests_per_minute,weight_per_minute=s.binance_weight_per_minute,state_store=redis)
    async def rest_error(exc, **ctx):
        # Every failed REST attempt (including retries) reaches the risk fallback and Prometheus.
        risk.observe(equity=latest_equity["value"], ws_connected=adapter.ws_connected if "adapter" in locals() else True, rest_error=True)
        observe_rest_error("LIVE", str(ctx.get("path","unknown")))
        logging.error("REST failure %s %s: %s", ctx.get("method"), ctx.get("path"), exc)
    rest.set_error_callback(rest_error)
    await rest.start()
    adapter=BinanceLiveExecutionAdapter(rest,db_logger=db,state_store=redis,state_key="execution:account:LIVE", account_window_bars=window, account_decision_interval_seconds=float(a.interval), account_max_age_ms=int(max(1000.0, a.interval * 3000.0)))
    stop=asyncio.Event()
    async def alert(result): logging.critical('LIVE RECONCILIATION MISMATCH: %s',result)
    try:
        await adapter.start()
        policy=TrainedPolicy.load_ensemble([x.strip() for x in a.ensemble_models.split(',') if x.strip()],algorithm=meta.get('algorithm', meta.get('hyperparameters',{}).get('algorithm','ppo'))) if a.ensemble_models else TrainedPolicy.load(a.model)
        store=BinanceFeatureStore(rest,a.symbol,intervals=('1m','5m','15m','1h'),redis=redis,db_pool=pool,regime_model_path=regime_model,checkpoint_metadata=meta,require_scaler=True,cross_asset_symbols=[x for x in s.symbol_list if x != a.symbol])
        training_values=[]
        training_frame=None
        if a.training_feature_values:
            import pandas as pd
            try:
                candidate=pd.read_csv(a.training_feature_values)
                numeric=candidate.select_dtypes(include='number')
                if numeric.shape[1] >= 2:
                    training_frame=numeric
                    risk.set_training_feature_frame(training_frame)
                else:
                    training_values=[float(x.strip()) for x in Path(a.training_feature_values).read_text().replace(',', '\n').split() if x.strip()]
            except Exception:
                training_values=[float(x.strip()) for x in Path(a.training_feature_values).read_text().replace(',', '\n').split() if x.strip()]
        elif meta.get('training_feature_frame_path') and Path(meta['training_feature_frame_path']).exists():
            import pandas as pd
            training_frame=pd.read_csv(meta['training_feature_frame_path']).select_dtypes(include='number')
            risk.set_training_feature_frame(training_frame)
        elif meta.get('training_feature_distribution'):
            training_values=[float(x) for x in meta['training_feature_distribution']]
        if training_values: risk.set_training_feature_distribution(training_values)
        if meta.get('oos_sharpe') is not None: risk.set_baseline_sharpe(meta['oos_sharpe'])
        elif s.live_sharpe_baseline is not None: risk.set_baseline_sharpe(s.live_sharpe_baseline)
        reconciler=Reconciler(adapter,db_logger=db,alert=alert)
        engine=PaperTradingEngine(policy=None,observation_builder=None,execution=adapter,symbol=a.symbol,quantity=Decimal(a.quantity),risk_manager=risk,capital_ramp=ramp,risk_event_logger=db)
        reconcile_task=asyncio.create_task(reconciler.run([a.symbol],a.reconcile_seconds,stop))
        supervisor=LiveGovernanceSupervisor(risk=risk,execution=adapter,reconciler=reconciler,config=GovernanceConfig(retrain_command=a.retrain_command),challenger=ChallengerPipeline(),on_pause=alert)
        await supervisor.start()
        try:
            while True:
                try:
                    # Steady-state account state is authoritative from the authenticated
                    # user-data stream. REST is reserved for adapter bootstrap/reconciliation.
                    account=adapter.account_snapshot(symbol=a.symbol, require_fresh=False)
                    equity=float(account.get('totalMarginBalance',account.get('totalWalletBalance',account.get('_equity',0))) or 0); latest_equity["value"]=equity
                    account["positions"]=[{"symbol":p.symbol,"positionAmt":str(p.position_amt),"entryPrice":str(p.entry_price),"markPrice":str(p.mark_price),"liquidationPrice":str(p.liquidation_price),"unRealizedProfit":str(p.unrealized_pnl),"leverage":str(p.leverage),"marginType":p.margin_type} for p in adapter.state.positions.values() if p.position_amt!=0]
                    await db.log_account_snapshot(account,mode="LIVE")
                except Exception: equity=latest_equity["value"] or 0.0
                def account_state():
                    return adapter.account_observation_async(a.symbol)
                obs=await store.get_observation(feature_columns,window=window,account=account_state)
                feature_values=obs['market'][-1].tolist() if hasattr(obs.get('market'),'__len__') else []
                prev=getattr(main, '_last_live_equity', None)
                ret=None if prev in (None,0) or equity<=0 else equity/prev-1.0
                main._last_live_equity=equity
                short_vol,vol_mean,vol_std=store.latest_market_volatility_stats(risk.cfg.vol_window)
                if training_frame is not None:
                    import pandas as pd
                    live_frame=pd.DataFrame([feature_values],columns=training_frame.columns[:len(feature_values)])
                    risk.observe_feature_frame(live_frame)
                risk.observe(equity=equity,return_t=ret,short_vol=short_vol,rolling_vol_mean=vol_mean,rolling_vol_std=vol_std,ws_connected=adapter.ws_connected,rest_error=False,feature_values=feature_values)
                _t0=time.perf_counter(); action=policy.predict(obs,deterministic=True); observe_inference("LIVE", Path(a.model).name, time.perf_counter()-_t0)
                await engine.execute_action(action)
                await asyncio.sleep(a.interval)
        finally:
            await supervisor.stop(); stop.set(); reconcile_task.cancel()
            try: await reconcile_task
            except asyncio.CancelledError: pass
    finally:
        await adapter.stop(); await rest.close(); await redis.aclose(); await pool.close()

if __name__=='__main__': asyncio.run(main())
