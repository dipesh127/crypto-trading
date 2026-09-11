from __future__ import annotations
import json
from datetime import datetime, timezone
try:
    from app.monitoring import observe_order, observe_fill, observe_order_latency, set_account_telemetry, set_margin_ratio
except Exception:
    observe_order=observe_fill=observe_order_latency=set_account_telemetry=set_margin_ratio=None

class ExecutionDBLogger:
    """Writes paper/testnet and future live execution records into one neutral schema."""
    def __init__(self, pool, mode="PAPER_TESTNET", dashboard_cache=None):
        self.pool = pool
        self.mode = mode
        self.dashboard_cache = dashboard_cache
        self.alert_dispatcher = None

    async def log_order(self, response, *, mode=None, latency_ms=0.0, request=None):
        mode = mode or self.mode
        async with self.pool.acquire() as c:
            await c.execute("""INSERT INTO execution.orders
                (mode, symbol, exchange_order_id, client_order_id, side, order_type, status,
                 orig_qty, executed_qty, avg_price, update_time, latency_ms, request, raw)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,to_timestamp($11/1000.0),$12,$13,$14)
                ON CONFLICT (mode, exchange_order_id, client_order_id) DO UPDATE SET
                  status=EXCLUDED.status, executed_qty=EXCLUDED.executed_qty,
                  avg_price=EXCLUDED.avg_price, update_time=EXCLUDED.update_time,
                  latency_ms=EXCLUDED.latency_ms, raw=EXCLUDED.raw""",
                mode, response.get("symbol",""), str(response.get("orderId","")), str(response.get("clientOrderId","")),
                response.get("side",""), response.get("type",""), response.get("status",""),
                response.get("origQty", response.get("orig_qty","0")), response.get("executedQty", response.get("cumQty","0")),
                response.get("avgPrice", response.get("avg_price","0")), int(response.get("updateTime", response.get("transactTime",0)) or 0),
                float(latency_ms), json.dumps(request or {}), json.dumps(response))
        if observe_order: observe_order(mode,response.get("symbol",""),response.get("side",""),response.get("status",""))
        if observe_order_latency: observe_order_latency(mode,response.get("symbol",""),float(latency_ms or 0)/1000.0)
        if self.dashboard_cache:
            await self.dashboard_cache.invalidate(*[k for k in (f"dash:overview:{mode}",f"dash:metrics:{mode}",f"dash:ts:equity:{mode}",f"dash:ts:drawdown:{mode}",f"dash:benchmarks:{mode}") if k])
    async def log_fill(self, fill, *, mode=None):
        mode = mode or self.mode
        async with self.pool.acquire() as c:
            await c.execute("""INSERT INTO execution.fills
                (mode,symbol,exchange_trade_id,exchange_order_id,client_order_id,side,price,qty,quote_qty,commission,commission_asset,trade_time,raw)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,to_timestamp($12/1000.0),$13)
                ON CONFLICT DO NOTHING""",
                mode, fill.get("s",""), str(fill.get("t",fill.get("tradeId",""))), str(fill.get("i",fill.get("orderId",""))),
                fill.get("c",fill.get("clientOrderId","")), fill.get("S",fill.get("side","")), fill.get("L",fill.get("price","0")),
                fill.get("l",fill.get("qty","0")), fill.get("nq",fill.get("quoteQty","0")), fill.get("n",fill.get("commission","0")),
                fill.get("N",fill.get("commissionAsset","USDT")), int(fill.get("T",fill.get("time",0)) or 0), json.dumps(fill))
        if observe_fill: observe_fill(mode,fill.get("s",fill.get("symbol","")),fill.get("S",fill.get("side","")))
        if self.dashboard_cache:
            await self.dashboard_cache.invalidate(*[k for k in (f"dash:overview:{mode}",f"dash:metrics:{mode}",f"dash:ts:equity:{mode}",f"dash:ts:drawdown:{mode}",f"dash:benchmarks:{mode}") if k])

    async def log_user_event(self, event):
        async with self.pool.acquire() as c:
            await c.execute("INSERT INTO execution.user_events(mode,event_time,event_type,payload) VALUES($1,to_timestamp($2/1000.0),$3,$4)",
                             self.mode, int(event.get("E",0)), event.get("e",""), json.dumps(event))

    async def log_reconciliation(self, result):
        async with self.pool.acquire() as c:
            await c.execute("INSERT INTO execution.reconciliation_events(mode,checked_at,ok,payload) VALUES($1,now(),$2,$3)",
                             self.mode, bool(result.get("ok")), json.dumps(result))

    async def log_ws_health(self, connected: bool, *, last_event_time_ms: int = 0, error: str | None = None):
        """Persist authenticated user-stream health/heartbeat state for the dashboard."""
        async with self.pool.acquire() as c:
            await c.execute("""INSERT INTO dashboard.ws_health
                (mode,ts,connected,last_event_time,last_error)
                VALUES($1,now(),$2,$3,$4)""",
                self.mode, bool(connected),
                datetime.fromtimestamp(last_event_time_ms/1000.0,tz=timezone.utc) if last_event_time_ms else None,
                error)
        if self.dashboard_cache:
            await self.dashboard_cache.invalidate(f"dash:overview:{self.mode}")


    async def log_account_snapshot(self, account, *, mode=None, today_pnl=None, leverage=None):
        """Persist the complete account/margin snapshot used by the dashboard.

        Binance account fields are normalized here so the dashboard does not have to
        reconstruct margin telemetry from user-stream deltas.
        """
        mode = mode or self.mode
        now = datetime.now(timezone.utc)
        equity = account.get("totalMarginBalance", account.get("totalWalletBalance"))
        wallet = account.get("totalWalletBalance")
        available = account.get("availableBalance")
        unrealized = account.get("totalUnrealizedProfit")
        initial = account.get("totalInitialMargin", account.get("totalPositionInitialMargin"))
        maint = account.get("totalMaintMargin")
        try:
            equity_f = float(equity) if equity is not None else None
            maint_f = float(maint) if maint is not None else None
            margin_ratio = (maint_f / equity_f) if equity_f and maint_f is not None else None
        except (TypeError, ValueError, ZeroDivisionError):
            margin_ratio = None
        lev = leverage
        if lev is None:
            positions = account.get("positions") or []
            notionals = 0.0
            for x in positions:
                # Binance account payload exposes notional on position objects.
                # Fall back to abs(positionAmt * markPrice) when notional is absent.
                n = x.get("notional")
                if n is None:
                    n = float(x.get("positionAmt", 0) or 0) * float(x.get("markPrice", 0) or 0)
                notionals += abs(float(n or 0))
            lev = (notionals / equity_f) if equity_f else None
        positions_payload = []
        for x in (account.get("positions") or []):
            positions_payload.append({
                "symbol": x.get("symbol", x.get("s")),
                "qty": float(x.get("positionAmt", x.get("pa", 0)) or 0),
                "entry_price": float(x.get("entryPrice", x.get("ep", 0)) or 0),
                "mark_price": float(x.get("markPrice", x.get("mp", 0)) or 0),
                "liquidation_price": float(x.get("liquidationPrice", x.get("li", 0)) or 0),
                "unrealized_pnl": float(x.get("unRealizedProfit", x.get("up", 0)) or 0),
                "leverage": float(x.get("leverage", x.get("l", 1)) or 1),
                "margin_type": x.get("marginType", x.get("mt", "ISOLATED")),
            })
        async with self.pool.acquire() as c:
            if today_pnl is None and equity_f is not None:
                baseline = await c.fetchval(
                    "SELECT equity FROM dashboard.account_snapshots WHERE mode=$1 AND ts >= date_trunc('day', now()) ORDER BY ts ASC LIMIT 1",
                    mode,
                )
                if baseline is not None:
                    today_pnl = equity_f - float(baseline)
            await c.execute("""INSERT INTO dashboard.account_snapshots
                (mode,ts,wallet_balance,available_balance,equity,unrealized_pnl,
                 total_initial_margin,total_maint_margin,margin_ratio,leverage,today_pnl,positions)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb)
                ON CONFLICT(mode,ts) DO UPDATE SET
                  wallet_balance=EXCLUDED.wallet_balance,available_balance=EXCLUDED.available_balance,
                  equity=EXCLUDED.equity,unrealized_pnl=EXCLUDED.unrealized_pnl,
                  total_initial_margin=EXCLUDED.total_initial_margin,total_maint_margin=EXCLUDED.total_maint_margin,
                  margin_ratio=EXCLUDED.margin_ratio,leverage=EXCLUDED.leverage,today_pnl=EXCLUDED.today_pnl,positions=EXCLUDED.positions""",
                mode, now, wallet, available, equity, unrealized, initial, maint, margin_ratio, lev, today_pnl, json.dumps(positions_payload))
            await c.execute("""INSERT INTO dashboard.equity_snapshots
                (mode,ts,equity,drawdown,unrealized_pnl,today_pnl,leverage,margin_ratio)
                VALUES($1,$2,$3,NULL,$4,$5,$6,$7)
                ON CONFLICT(mode,ts) DO UPDATE SET equity=EXCLUDED.equity,
                  unrealized_pnl=EXCLUDED.unrealized_pnl,today_pnl=EXCLUDED.today_pnl,
                  leverage=EXCLUDED.leverage,margin_ratio=EXCLUDED.margin_ratio""",
                mode, now, equity, unrealized, today_pnl, lev, margin_ratio)
        if set_account_telemetry:
            try:
                notionals=sum(abs(float(x.get("qty",0)))*abs(float(x.get("mark_price",0))) for x in positions_payload)
                if equity_f is not None: set_account_telemetry(mode,equity=equity_f,exposure=notionals)
                if set_margin_ratio and margin_ratio is not None: set_margin_ratio(mode,margin_ratio)
                if mode and notionals is not None:
                    from app.monitoring import set_position_telemetry
                    set_position_telemetry(mode,positions_payload)
            except Exception: pass
        if self.dashboard_cache:
            await self.dashboard_cache.invalidate(*[k for k in (f"dash:overview:{mode}",f"dash:metrics:{mode}",f"dash:ts:equity:{mode}",f"dash:ts:drawdown:{mode}",f"dash:benchmarks:{mode}") if k])


    async def reconstruct_position_opened_at(self, mode, symbol, current_qty, position_side="BOTH"):
        """Reconstruct the current position's opening time from the durable fill journal."""
        from app.execution.lifecycle import reconstruct_opened_at_ms
        target = float(current_qty or 0)
        if abs(target) < 1e-15:
            return 0
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                """SELECT side, qty, trade_time, raw, exchange_trade_id
                   FROM execution.fills
                   WHERE mode=$1 AND symbol=$2
                   ORDER BY trade_time ASC, exchange_trade_id ASC""",
                mode, symbol,
            )
        trades = []
        for row in rows:
            raw = row["raw"] or {}
            trades.append({
                "side": row["side"],
                "qty": row["qty"],
                "time": int(row["trade_time"].timestamp() * 1000),
                "id": int(row["exchange_trade_id"]) if str(row["exchange_trade_id"]).isdigit() else 0,
                "positionSide": raw.get("ps", position_side),
            })
        return reconstruct_opened_at_ms(trades, target, position_side=position_side)

    async def load_position_open_state(self, mode, symbol):
        async with self.pool.acquire() as c:
            row = await c.fetchrow(
                "SELECT opened_at_ms, open_time_known FROM execution.position_lifecycle WHERE mode=$1 AND symbol=$2",
                mode, symbol,
            )
        if not row:
            return None, False
        known = bool(row["open_time_known"]) and row["opened_at_ms"] is not None
        return (int(row["opened_at_ms"]) if known else None), known

    async def load_position_opened_at(self, mode, symbol):
        opened_at, known = await self.load_position_open_state(mode, symbol)
        return opened_at if known else None

    async def save_position_open_state(self, mode, symbol, opened_at_ms, *, known: bool) -> None:
        async with self.pool.acquire() as c:
            if known and opened_at_ms and int(opened_at_ms) > 0:
                await c.execute(
                    """INSERT INTO execution.position_lifecycle(mode,symbol,opened_at_ms,open_time_known,updated_at)
                       VALUES($1,$2,$3,TRUE,now())
                       ON CONFLICT(mode,symbol) DO UPDATE
                       SET opened_at_ms=EXCLUDED.opened_at_ms, open_time_known=TRUE, updated_at=now()""",
                    mode, symbol, int(opened_at_ms),
                )
            else:
                await c.execute(
                    """INSERT INTO execution.position_lifecycle(mode,symbol,opened_at_ms,open_time_known,updated_at)
                       VALUES($1,$2,NULL,FALSE,now())
                       ON CONFLICT(mode,symbol) DO UPDATE
                       SET opened_at_ms=NULL, open_time_known=FALSE, updated_at=now()""",
                    mode, symbol,
                )

    async def save_position_opened_at(self, mode, symbol, opened_at_ms):
        await self.save_position_open_state(mode, symbol, opened_at_ms, known=bool(opened_at_ms))

    def set_alert_dispatcher(self, dispatcher):
        self.alert_dispatcher=dispatcher

    async def log_risk_event(self, decision, *, mode=None, metrics=None):
        mode = mode or self.mode
        async with self.pool.acquire() as c:
            await c.execute("""INSERT INTO execution.risk_events(mode,event_time,allowed,action,reasons,flatten,metrics)
                VALUES($1,now(),$2,$3,$4,$5,$6::jsonb)""", mode, bool(decision.allowed), int(decision.action),
                list(decision.reasons), bool(decision.flatten), json.dumps(metrics or {}))
        if self.dashboard_cache:
            await self.dashboard_cache.invalidate(*[k for k in (f"dash:overview:{mode}",f"dash:metrics:{mode}",f"dash:ts:equity:{mode}",f"dash:ts:drawdown:{mode}",f"dash:benchmarks:{mode}") if k])
        if self.alert_dispatcher:
            try:
                await self.alert_dispatcher.risk(mode, decision, metrics)
            except Exception:
                import logging; logging.getLogger(__name__).exception("risk alert failed")
