from __future__ import annotations
import argparse, asyncio, json, time
from app.config import get_settings

QUERIES=[
("overview_orders","SELECT symbol,side,status,executed_qty::float8 AS executed_qty,avg_price::float8 AS avg_price,update_time,mode FROM execution.orders WHERE mode='PAPER_TESTNET' ORDER BY update_time DESC,exchange_order_id DESC LIMIT 100"),
("overview_fills","SELECT symbol,side,price,qty,commission,trade_time FROM execution.fills WHERE mode='PAPER_TESTNET' ORDER BY trade_time DESC,exchange_trade_id DESC LIMIT 100"),
("metrics_orders","SELECT COUNT(*) trade_count,COALESCE(SUM(executed_qty),0)::float8 turnover,COALESCE(AVG(latency_ms),0)::float8 avg_latency FROM execution.orders WHERE mode='PAPER_TESTNET'"),
("equity_5m","SELECT bucket,equity FROM dashboard.equity_5m WHERE mode='PAPER_TESTNET' AND bucket>=now()-interval '90 days' ORDER BY bucket"),
("equity_1h","SELECT bucket,equity FROM dashboard.equity_1h WHERE mode='PAPER_TESTNET' AND bucket>=now()-interval '3 years' ORDER BY bucket"),
("price_1h","SELECT bucket,open,high,low,close,volume FROM market.klines_1h WHERE symbol='BTCUSDT' AND bucket>=now()-interval '90 days' ORDER BY bucket"),
("signals","SELECT symbol,ts,signal,price FROM dashboard.signal_events WHERE mode='PAPER_TESTNET' AND symbol='BTCUSDT' AND ts>=now()-interval '30 days' ORDER BY ts DESC LIMIT 500"),
("alerts","SELECT event_time,allowed,action,reasons,metrics FROM execution.risk_events WHERE mode='PAPER_TESTNET' ORDER BY event_time DESC LIMIT 100"),
("metric_history","SELECT ts,sharpe,sortino,calmar,max_drawdown,win_rate,profit_factor,expectancy,trade_count FROM dashboard.metric_snapshots WHERE mode='PAPER_TESTNET' ORDER BY ts DESC LIMIT 500"),
("benchmarks","SELECT benchmark,period_start,period_end,total_return,sharpe,max_drawdown,trade_count FROM dashboard.benchmark_snapshots WHERE mode='PAPER_TESTNET' ORDER BY period_end DESC LIMIT 100"),
]
REQUIRED_INDEXES={
'execution.orders':['idx_exec_orders_dash_cursor','idx_exec_orders_dash_symbol','idx_exec_orders_dash_qty','idx_exec_orders_dash_avg'],
'execution.fills':['idx_exec_fills_dash_time'],
'dashboard.equity_snapshots':['idx_dash_equity_mode_ts'],
'dashboard.signal_events':['idx_dash_signal_symbol_ts'],
'dashboard.metric_snapshots':['idx_dash_metric_mode_ts'],
'market.klines_1h':['idx_klines_1h_dash'],
}

def flatten(node):
 out=[node.get('Node Type','')]; out.extend(x for c in node.get('Plans',[]) for x in flatten(c)); return out

async def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--json',action='store_true'); ap.add_argument('--max-ms',type=float,default=2000.0); args=ap.parse_args()
 from app.config import get_settings
 import asyncpg
 s=get_settings(); pool=await asyncpg.create_pool(s.postgres_dsn,min_size=1,max_size=2); report={'queries':{},'indexes':{},'ok':True,'max_ms':args.max_ms}
 try:
  async with pool.acquire() as c:
   idx_rows=await c.fetch("SELECT schemaname,tablename,indexname FROM pg_indexes WHERE schemaname IN ('execution','dashboard','market')")
   present={(r['schemaname']+'.'+r['tablename'],r['indexname']) for r in idx_rows}
   for table,names in REQUIRED_INDEXES.items():
    report['indexes'][table]={n:(table,n) in present for n in names}
    if not all(report['indexes'][table].values()): report['ok']=False
   for name,q in QUERIES:
    started=time.perf_counter();
    try:
     rows=await c.fetch('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '+q); elapsed=(time.perf_counter()-started)*1000
     plan=rows[0]['QUERY PLAN'][0] if rows else {}
     nodes=flatten(plan.get('Plan',{})); report['queries'][name]={'elapsed_ms':elapsed,'nodes':nodes}
     if elapsed>args.max_ms: report['ok']=False
    except Exception as exc:
     report['queries'][name]={'error':str(exc)}; report['ok']=False
 finally: await pool.close()
 if args.json: print(json.dumps(report,indent=2,default=str))
 else: print(json.dumps(report,indent=2,default=str))
 return 0 if report['ok'] else 2
if __name__=='__main__': raise SystemExit(asyncio.run(main()))
