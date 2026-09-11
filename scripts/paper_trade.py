#!/usr/bin/env python3
import argparse, asyncio, logging, json, time
from decimal import Decimal
from pathlib import Path
import asyncpg
from app.config import get_settings
from app.binance import BinanceREST
from app.paper import BinancePaperExecutionAdapter, PaperTradingEngine
from app.reconciliation import Reconciler
from app.db import ExecutionDBLogger
from app.rl.live_policy import TrainedPolicy
from app.rl.realtime import BinanceFeatureStore
from redis import asyncio as redis_asyncio
from app.risk.manager import RiskManager, RiskConfig
from app.alerts import AlertDispatcher
from app.monitoring import observe_inference, observe_rest_error, set_account_telemetry

async def main():
    p=argparse.ArgumentParser(description='Run a trained policy against Binance USD-M Futures Testnet')
    p.add_argument('--model',required=True)
    p.add_argument('--ensemble-models',default='',help='Comma-separated checkpoints for weighted voting ensemble'); p.add_argument('--metadata',required=True)
    p.add_argument('--symbol',default='BTCUSDT'); p.add_argument('--quantity',required=True); p.add_argument('--interval',type=float,default=60.0)
    p.add_argument('--reconcile-seconds',type=float,default=30.0)
    a=p.parse_args(); s=get_settings()
    if s.app_env.lower()!='testnet': raise SystemExit('Refusing to paper trade unless APP_ENV=testnet')
    if not s.binance_api_key or not s.binance_api_secret: raise SystemExit('Set BINANCE_API_KEY and BINANCE_API_SECRET in .env')
    meta=json.loads(Path(a.metadata).read_text()); feature_columns=meta['feature_columns']; window=int(meta.get('observation_window',60)); regime_model=meta.get('regime_model')
    if not regime_model or not Path(regime_model).exists(): raise SystemExit('Persisted training regime model is required; live/paper inference will not fit a regime model')
    logging.basicConfig(level=s.log_level)
    risk=RiskManager(RiskConfig())
    if meta.get('oos_sharpe') is not None: risk.set_baseline_sharpe(meta['oos_sharpe'])
    elif s.live_sharpe_baseline is not None: risk.set_baseline_sharpe(s.live_sharpe_baseline)
    latest_equity={"value": None}
    pool=await asyncpg.create_pool(s.postgres_dsn)
    db=ExecutionDBLogger(pool,mode='PAPER_TESTNET')
    db.set_alert_dispatcher(AlertDispatcher.from_env())
    redis=redis_asyncio.from_url(s.redis_url,decode_responses=True)
    rest=BinanceREST(s.binance_rest_base_url,s.binance_api_key,s.binance_api_secret,s.binance_recv_window_ms,s.binance_ws_base_url,raw_requests_per_minute=s.binance_raw_requests_per_minute,order_requests_per_minute=s.binance_order_requests_per_minute,weight_per_minute=s.binance_weight_per_minute,state_store=redis)
    adapter=BinancePaperExecutionAdapter(rest,db_logger=db,state_store=redis,state_key="execution:account:PAPER_TESTNET", account_window_bars=window, account_decision_interval_seconds=float(a.interval), account_max_age_ms=int(max(1000.0, a.interval * 3000.0)))
    async def rest_error(exc, **ctx):
        risk.observe(equity=latest_equity["value"], ws_connected=adapter.ws_connected, rest_error=True)
        observe_rest_error("PAPER_TESTNET", str(ctx.get("path","unknown"))); logging.error("PAPER REST failure %s %s: %s", ctx.get("method"), ctx.get("path"), exc)
    rest.set_error_callback(rest_error)
    await rest.start()
    stop=asyncio.Event()
    async def alert(result): logging.error('PAPER RECONCILIATION MISMATCH: %s',result)
    try:
        await adapter.start()
        policy=TrainedPolicy.load_ensemble([x.strip() for x in a.ensemble_models.split(',') if x.strip()],algorithm=meta.get('algorithm', meta.get('hyperparameters',{}).get('algorithm','ppo'))) if a.ensemble_models else TrainedPolicy.load(a.model)
        store=BinanceFeatureStore(rest,a.symbol,intervals=('1m','5m','15m','1h'),redis=redis,db_pool=pool,regime_model_path=regime_model,checkpoint_metadata=meta,require_scaler=True,cross_asset_symbols=[x for x in s.symbol_list if x != a.symbol])
        reconciler=Reconciler(adapter,db_logger=db,alert=alert)
        def risk_context():
            short_vol,vol_mean,vol_std=store.latest_market_volatility_stats(risk.cfg.vol_window)
            return {"short_vol":short_vol,"rolling_vol_mean":vol_mean,"rolling_vol_std":vol_std}
        engine=PaperTradingEngine(policy=None,observation_builder=None,execution=adapter,symbol=a.symbol,quantity=Decimal(a.quantity),risk_manager=risk,risk_event_logger=db,risk_context_provider=risk_context)
        reconcile_task=asyncio.create_task(reconciler.run([a.symbol],a.reconcile_seconds,stop))
        try:
            while True:
                try:
                    account=adapter.account_snapshot(symbol=a.symbol, require_fresh=False)
                    latest_equity["value"]=float(account.get("_equity",account.get("totalWalletBalance",0)) or 0)
                    if account:
                        account["positions"]=[{"symbol":p.symbol,"positionAmt":str(p.position_amt),"entryPrice":str(p.entry_price),"markPrice":str(p.mark_price),"liquidationPrice":str(p.liquidation_price),"unRealizedProfit":str(p.unrealized_pnl),"leverage":str(p.leverage),"marginType":p.margin_type} for p in adapter.state.positions.values() if p.position_amt!=0]
                        await db.log_account_snapshot(account,mode="PAPER_TESTNET")
                except Exception: pass
                def account_state():
                    return adapter.account_observation_async(a.symbol)
                obs=await store.get_observation(feature_columns,window=window,account=account_state)
                _t0=time.perf_counter(); action=policy.predict(obs,deterministic=True); observe_inference("PAPER_TESTNET", Path(a.model).name, time.perf_counter()-_t0)
                await engine.execute_action(action)
                latest_equity["value"]=engine.last_equity or latest_equity["value"]
                await asyncio.sleep(a.interval)
        finally:
            stop.set(); reconcile_task.cancel()
            try: await reconcile_task
            except asyncio.CancelledError: pass
    finally:
        await adapter.stop(); await rest.close(); await redis.aclose(); await pool.close()

if __name__=='__main__': asyncio.run(main())
