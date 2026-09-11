from __future__ import annotations
from datetime import datetime, timezone

async def persist_metric_snapshot(pool, mode, metrics):
    """Persist a bounded metric snapshot for dashboard trends/sparklines."""
    fields=('sharpe','sortino','calmar','max_drawdown','win_rate','profit_factor','expectancy','trade_count','average_holding_minutes')
    values=[metrics.get(k) for k in fields]
    async with pool.acquire() as c:
        await c.execute("""INSERT INTO dashboard.metric_snapshots
          (mode,ts,sharpe,sortino,calmar,max_drawdown,win_rate,profit_factor,expectancy,trade_count,average_holding_minutes)
          VALUES($1,now(),$2,$3,$4,$5,$6,$7,$8,$9,$10)""",mode,*values)
