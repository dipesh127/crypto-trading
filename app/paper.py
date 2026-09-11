from __future__ import annotations
import asyncio, json, logging, time, uuid, hashlib
try:
    from app.monitoring import observe_risk_veto
except Exception:
    observe_risk_veto=None
from .risk.manager import RiskDecision
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable, Mapping

from .binance import BinanceREST
from .execution.lifecycle import reconstruct_opened_at_ms
from .execution.position_lifecycle import PositionLifecycleService
from .rl.account_state import AccountSnapshot, AccountObservationProvider, PositionSnapshot

log = logging.getLogger(__name__)


@dataclass
class InternalOrder:
    client_order_id: str
    symbol: str
    side: str
    type: str
    orig_qty: Decimal
    status: str = "NEW"
    exchange_order_id: str | None = None
    executed_qty: Decimal = Decimal("0")
    avg_price: Decimal = Decimal("0")
    update_time_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class InternalPosition:
    symbol: str
    position_amt: Decimal = Decimal("0")
    entry_price: Decimal = Decimal("0")
    mark_price: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    liquidation_price: Decimal = Decimal("0")
    isolated_wallet: Decimal = Decimal("0")
    margin_type: str = "ISOLATED"
    leverage: Decimal = Decimal("1")
    opened_at_ms: int = 0
    open_time_known: bool = False


class ExecutionState:
    """Canonical local state reconstructed from REST bootstrap + user-data events."""
    def __init__(self):
        self.orders: dict[str, InternalOrder] = {}
        self.positions: dict[str, InternalPosition] = {}
        self.last_event_time_ms: int = 0
        self.last_user_stream_message_time_ms: int = 0
        self.last_user_stream_transport_activity_time_ms: int = 0
        self.last_account_state_update_time_ms: int = 0
        # None means transport-health tracking has not been wired (e.g. unit-level state object);
        # the live adapter sets explicit True/False values once the authenticated socket starts.
        self.user_stream_connected: bool | None = None
        self.user_stream_authenticated: bool | None = None
        self._state_version: tuple[int, int, int] = (0, 0, 0)
        self._state_version_seq: int = 0
        self.last_reconcile: dict[str, Any] | None = None
        self.account_snapshot: dict[str, Any] = {}
        self._pending_opened_at_ms: dict[str, int] = {}
        self._hot_state_updated_at_ms: int = 0

    def note_user_stream_message(self, *, received_at_ms: int | None = None) -> None:
        ts = int(received_at_ms if received_at_ms is not None else time.time() * 1000)
        self.last_user_stream_message_time_ms = max(self.last_user_stream_message_time_ms, ts)
        self.last_user_stream_transport_activity_time_ms = max(self.last_user_stream_transport_activity_time_ms, ts)

    def note_user_stream_transport_activity(self, *, received_at_ms: int | None = None) -> None:
        ts = int(received_at_ms if received_at_ms is not None else time.time() * 1000)
        self.last_user_stream_transport_activity_time_ms = max(self.last_user_stream_transport_activity_time_ms, ts)

    def _accept_state_version(self, *, source_priority: int, event_time_ms: int, arrival_time_ms: int | None = None) -> bool:
        self._state_version_seq += 1
        candidate = (int(source_priority), int(event_time_ms or 0), self._state_version_seq)
        if candidate < self._state_version:
            return False
        self._state_version = candidate
        return True

    def apply_order_update(self, event: dict[str, Any]) -> None:
        o = event.get("o", event)
        cid = str(o.get("c") or o.get("clientOrderId") or "")
        if not cid:
            return
        order = self.orders.get(cid)
        if order is None:
            order = InternalOrder(
                client_order_id=cid,
                symbol=str(o.get("s", "")),
                side=str(o.get("S", "")),
                type=str(o.get("o", o.get("type", ""))),
                orig_qty=Decimal(str(o.get("q", o.get("origQty", "0")))),
            )
            self.orders[cid] = order
        order.exchange_order_id = str(o.get("i", o.get("orderId", order.exchange_order_id or "")))
        order.status = str(o.get("X", o.get("status", order.status)))
        order.executed_qty = Decimal(str(o.get("z", o.get("executedQty", order.executed_qty))))
        order.avg_price = Decimal(str(o.get("ap", o.get("avgPrice", order.avg_price))))
        order.update_time_ms = int(o.get("T", o.get("updateTime", event.get("E", order.update_time_ms))))
        order.raw = dict(o)
        self.last_event_time_ms = max(self.last_event_time_ms, int(event.get("E", 0)))

    def apply_trade_update(self, event: dict[str, Any]) -> None:
        """Record an execution timestamp that should become the position-open time.

        ACCOUNT_UPDATE can arrive after ORDER_TRADE_UPDATE, so the trade event is
        retained as a candidate opening timestamp and consumed when account state lands.
        """
        o = event.get("o", event)
        if str(o.get("x", "TRADE")).upper() != "TRADE":
            return
        symbol = str(o.get("s", ""))
        if not symbol:
            return
        qty = abs(Decimal(str(o.get("l", o.get("executedQty", "0")) or 0)))
        if qty == 0:
            return
        side = str(o.get("S", o.get("side", ""))).upper()
        signed = qty if side == "BUY" else -qty if side == "SELL" else Decimal("0")
        if signed == 0:
            return
        current = self.positions.get(symbol)
        previous = current.position_amt if current else Decimal("0")
        # For BOTH/one-way mode, use the local position direction. The account update
        # remains authoritative; this timestamp only supplies the lifecycle start.
        if previous == 0 or previous * (previous + signed) < 0:
            trade_ts = int(o.get("T", event.get("E", 0)) or 0)
            existing = int(self._pending_opened_at_ms.get(symbol, 0) or 0)
            # ACCOUNT_UPDATE may lag multiple ORDER_TRADE_UPDATE fills. Preserve
            # the earliest candidate so the lifecycle starts at the first fill,
            # not the last fill observed before the account event lands.
            self._pending_opened_at_ms[symbol] = (
                min(existing, trade_ts) if existing and trade_ts else max(existing, trade_ts)
            )

    def apply_account_update(self, event: dict[str, Any]) -> None:
        a = event.get("a", {})
        event_time_ms = int(event.get("E", 0) or 0)
        if not self._accept_state_version(source_priority=30, event_time_ms=event_time_ms, arrival_time_ms=int(time.time() * 1000)):
            return
        balances = a.get("B") or []
        wallet = None
        if balances:
            self.account_snapshot["balances"] = [dict(b) for b in balances]
            usdt = next((b for b in balances if str(b.get("a", "")).upper() == "USDT"), None)
            if usdt is not None and usdt.get("wb") is not None:
                try:
                    wallet = float(usdt.get("wb") or 0.0)
                    self.account_snapshot["totalWalletBalance"] = wallet
                except (TypeError, ValueError):
                    wallet = None
        if self.last_user_stream_message_time_ms <= 0:
            self.last_user_stream_message_time_ms = event_time_ms or int(time.time() * 1000)
        self.account_snapshot["_source"] = "authenticated_user_stream"
        self.account_snapshot["_authoritative"] = True
        # A post-reconnect authenticated update also proves the account stream is
        # current, so it satisfies a pending REST recovery gate.
        self.account_snapshot.pop("_recovery_required", None)
        self.account_snapshot["_last_event_time_ms"] = event_time_ms
        self.account_snapshot["_last_account_state_update_time_ms"] = event_time_ms
        self.account_snapshot["_last_user_stream_message_time_ms"] = self.last_user_stream_message_time_ms
        self.last_account_state_update_time_ms = event_time_ms
        for p in a.get("P", []):
            symbol = str(p.get("s", ""))
            prev=self.positions.get(symbol)
            qty=Decimal(str(p.get("pa", "0")))
            candidate = int(self._pending_opened_at_ms.pop(symbol, 0) or 0)
            same_run = bool(prev and prev.position_amt != 0 and qty != 0 and prev.position_amt * qty > 0)
            opened_at = prev.opened_at_ms if same_run else (candidate if qty != 0 else 0)
            open_time_known = bool(prev.open_time_known) if same_run and prev else bool(candidate and qty != 0)
            if qty != 0 and not opened_at:
                open_time_known = False
            self.positions[symbol] = InternalPosition(
                symbol=symbol, position_amt=qty, entry_price=Decimal(str(p.get("ep", "0"))),
                mark_price=Decimal(str(p.get("mp", "0"))), unrealized_pnl=Decimal(str(p.get("up", "0"))),
                liquidation_price=Decimal(str(p.get("li", p.get("liquidationPrice", "0")))), isolated_wallet=Decimal(str(p.get("iw", "0"))),
                margin_type=str(p.get("mt", "ISOLATED")), leverage=Decimal(str(p.get("l", "1"))), opened_at_ms=opened_at, open_time_known=open_time_known)
        # Recompute equity only after all position updates have been applied, so an
        # ACCOUNT_UPDATE containing fresh uPnL cannot be combined with stale positions.
        if wallet is not None:
            total_up = sum(float(p.unrealized_pnl) for p in self.positions.values())
            self.account_snapshot["_equity"] = wallet + total_up
            self.account_snapshot["_equity_definition"] = "totalWalletBalance_plus_position_unrealized_pnl"
        self.last_event_time_ms = max(self.last_event_time_ms, int(event.get("E", 0) or 0))

    def apply_hot_state_payload(self, payload: Mapping[str, Any]) -> bool:
        """Merge a newer shared Redis account-state projection into local state."""
        updated_at_ms = int(payload.get("updated_at_ms", 0) or 0)
        if updated_at_ms <= self._hot_state_updated_at_ms:
            return False
        source = str(payload.get("source", ""))
        authoritative = bool(payload.get("authoritative", False))
        incoming_event = int(payload.get("last_state_event_time_ms", payload.get("last_event_time_ms", 0)) or 0)
        source_priority = int(payload.get("last_state_source_priority", 30 if authoritative and source == "authenticated_user_stream" else 10))
        if not self._accept_state_version(source_priority=source_priority, event_time_ms=incoming_event or updated_at_ms, arrival_time_ms=updated_at_ms):
            return False
        self._hot_state_updated_at_ms = updated_at_ms
        account = dict(payload.get("account") or {})
        if not account:
            return False
        self.account_snapshot = account
        self.account_snapshot["_source"] = source or self.account_snapshot.get("_source", "redis_hot_state")
        self.account_snapshot["_authoritative"] = authoritative
        if incoming_event:
            self.account_snapshot["_last_event_time_ms"] = incoming_event
        self.last_user_stream_message_time_ms = max(
            self.last_user_stream_message_time_ms,
            int(account.get("_last_user_stream_message_time_ms", 0) or 0),
        )
        self.last_user_stream_transport_activity_time_ms = max(
            self.last_user_stream_transport_activity_time_ms,
            int(account.get("_last_user_stream_transport_activity_time_ms", 0) or 0),
        )
        positions_payload = payload.get("positions") or {}
        for symbol, raw in positions_payload.items():
            self.positions[str(symbol)] = InternalPosition(
                symbol=str(raw.get("symbol", symbol)),
                position_amt=Decimal(str(raw.get("position_amt", "0"))),
                entry_price=Decimal(str(raw.get("entry_price", "0"))),
                mark_price=Decimal(str(raw.get("mark_price", "0"))),
                unrealized_pnl=Decimal(str(raw.get("unrealized_pnl", "0"))),
                liquidation_price=Decimal(str(raw.get("liquidation_price", "0"))),
                leverage=Decimal(str(raw.get("leverage", "1"))),
                margin_type=str(raw.get("margin_type", "ISOLATED")),
                opened_at_ms=int(raw.get("opened_at_ms", 0) or 0),
                open_time_known=bool(raw.get("open_time_known", False)),
            )
        return True

    def is_account_state_fresh(
        self, *, now_ms: int | None = None, max_age_ms: int = 5000,
        allow_bootstrap: bool = False, ws_connected: bool = False,
        require_user_stream_health: bool = False, transport_max_age_ms: int | None = None,
    ) -> bool:
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        if bool(self.account_snapshot.get("_recovery_required", False)):
            return False
        source = str(self.account_snapshot.get("_source", ""))
        if source == "authenticated_user_stream" and bool(self.account_snapshot.get("_authoritative", False)):
            # Account values may remain unchanged for hours. State freshness is therefore
            # governed by authenticated user-stream liveness, not account-change frequency.
            transport_ts = int(self.last_user_stream_transport_activity_time_ms or self.last_user_stream_message_time_ms or 0)
            transport_limit = int(transport_max_age_ms if transport_max_age_ms is not None else max_age_ms)
            if self.user_stream_connected is None or self.user_stream_authenticated is None:
                stream_healthy = bool(ws_connected)
            else:
                stream_healthy = bool(ws_connected) and bool(self.user_stream_connected) and bool(self.user_stream_authenticated)
            # Account values may legitimately remain unchanged for long periods. Once
            # an authenticated user stream is healthy, transport liveness—not the age
            # of the last ACCOUNT_UPDATE—is what determines whether the cached account
            # snapshot is safe to use. The account-change timestamp remains diagnostic.
            return transport_ts > 0 and 0 <= now - transport_ts <= transport_limit and (not require_user_stream_health or stream_healthy)
        if source == "rest_bootstrap" and allow_bootstrap:
            bootstrap_ts = int(self.account_snapshot.get("_bootstrap_time_ms", 0) or 0)
            return bool(ws_connected) and bootstrap_ts > 0 and 0 <= now - bootstrap_ts <= int(max_age_ms)
        return False

    def account_snapshot_for(
        self, symbol: str, *, now_ms: int | None = None, max_age_ms: int = 5000,
        allow_bootstrap: bool = False, ws_connected: bool = False,
        require_user_stream_health: bool = False, require_open_time_known: bool = False,
        transport_max_age_ms: int | None = None,
    ) -> AccountSnapshot:
        if not self.is_account_state_fresh(now_ms=now_ms, max_age_ms=max_age_ms, allow_bootstrap=allow_bootstrap, ws_connected=ws_connected, require_user_stream_health=require_user_stream_health, transport_max_age_ms=transport_max_age_ms):
            raise RuntimeError("account state is stale, unavailable, or user-stream is unhealthy")
        pos = self.positions.get(symbol)
        equity = float(self.account_snapshot.get("_equity", self.account_snapshot.get("totalWalletBalance", 0.0)) or 0.0)
        if pos is None:
            return AccountSnapshot(equity=equity)
        open_time_known = bool(getattr(pos, "open_time_known", True))
        if pos.position_amt != 0 and require_open_time_known and not open_time_known:
            raise RuntimeError(f"position open time is unknown for {symbol}; refusing account observation")
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        age_s = max(0.0, (now - int(pos.opened_at_ms)) / 1000.0) if pos.position_amt != 0 and pos.opened_at_ms and open_time_known else 0.0
        return AccountSnapshot(
            equity=equity,
            maintenance_margin=float(self.account_snapshot.get("totalMaintMargin", 0.0) or 0.0),
            position=PositionSnapshot(
                position_qty=float(pos.position_amt),
                mark_price=float(pos.mark_price),
                unrealized_pnl=float(pos.unrealized_pnl),
                leverage=float(pos.leverage),
                time_in_position_seconds=age_s,
                open_time_known=open_time_known,
            ),
        )


class BinancePaperExecutionAdapter:
    """Real Binance USD-M Testnet execution adapter.

    This is deliberately not a simulator: orders are submitted to the configured
    Binance REST endpoint and state is consumed from the authenticated user stream.
    The adapter refuses non-testnet endpoints by default.
    """
    def __init__(self, rest: BinanceREST, *, testnet_only: bool = True,
                 allow_live: bool = False, db_logger=None, execution_mode: str = "PAPER_TESTNET",
                 state_store=None, state_key: str | None = None,
                 account_window_bars: int = 60, account_decision_interval_seconds: float = 60.0,
                 account_max_age_ms: int = 5000, require_ws_for_trading: bool = True,
                 ws_start_timeout_seconds: float = 15.0, hot_state_poll_seconds: float = 0.25,
                 user_stream_max_silence_ms: int = 30000, bootstrap_max_age_ms: int = 30000):
        if execution_mode not in {"PAPER_TESTNET", "LIVE"}:
            raise ValueError("execution_mode must be PAPER_TESTNET or LIVE")
        self.rest = rest
        self.execution_mode = execution_mode
        self.testnet_only = testnet_only
        self.allow_live = allow_live
        self.db_logger = db_logger
        self.state_store = state_store
        self.state_key = state_key or f"execution:account:{execution_mode}"
        self.state = ExecutionState()
        self._account_observation_provider = AccountObservationProvider(
            self._canonical_account_snapshot,
            window_bars=account_window_bars,
            bar_seconds=account_decision_interval_seconds,
            max_age_ms=account_max_age_ms,
        )
        self._account_max_age_ms = int(account_max_age_ms)
        self._user_stream_max_silence_ms = int(user_stream_max_silence_ms)
        self._user_stream_transport_max_age_ms = int(user_stream_max_silence_ms)
        self._account_state_freshness_policy = {
            "user_stream_state_max_age_ms": self._user_stream_max_silence_ms,
            "user_stream_transport_max_age_ms": self._user_stream_transport_max_age_ms,
            "bootstrap_state_max_age_ms": int(bootstrap_max_age_ms),
        }
        self._bootstrap_max_age_ms = int(bootstrap_max_age_ms)
        self.require_ws_for_trading = bool(require_ws_for_trading)
        self.ws_start_timeout_seconds = float(ws_start_timeout_seconds)
        self.hot_state_poll_seconds = float(hot_state_poll_seconds)
        self._hot_state_task: asyncio.Task | None = None
        self._hot_state_updated_at_ms: int = 0
        self._listen_key: str | None = None
        self._ws_task: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._health_task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()
        self._event_callbacks: list[Callable[[dict[str, Any]], Awaitable[None] | None]] = []
        self._idempotency: dict[str, dict[str, Any]] = {}
        self._last_ws_error_time: float | None = None
        self._user_stream_recovery_pending = False
        self._rest_error_count = 0
        self.ws_connected = False
        if self.testnet_only and not self.allow_live and "testnet" not in self.rest.base_url.lower():
            raise ValueError("Paper adapter is testnet-only; Binance REST base URL is not a Testnet URL")

    def add_event_callback(self, callback):
        self._event_callbacks.append(callback)

    def _canonical_account_snapshot(self, symbol: str, *, now_ms: int | None = None, max_age_ms: int = 5000) -> AccountSnapshot:
        """Single adapter-owned account-state contract for observation/risk callers.

        Bootstrap state is permitted only after the authenticated user-data websocket is
        connected. Once a user-stream account update is received, that stream becomes the
        authoritative source and stale/disconnected state is rejected.
        """
        return self.state.account_snapshot_for(
            symbol,
            now_ms=now_ms,
            max_age_ms=self._user_stream_max_silence_ms if self.state.account_snapshot.get("_source") == "authenticated_user_stream" else self._bootstrap_max_age_ms,
            allow_bootstrap=True,
            ws_connected=self.ws_connected,
            require_user_stream_health=True,
            require_open_time_known=True,
            transport_max_age_ms=self._user_stream_transport_max_age_ms,
        )

    @property
    def account_state_freshness_policy(self) -> dict[str, int]:
        return dict(self._account_state_freshness_policy)

    async def _publish_authoritative_state(self) -> None:
        """Mirror authenticated user-stream state into Redis hot state.

        Redis is the shared low-latency hot-state projection. ExecutionState is the
        local projection consumed by the canonical observation builder; it is continuously
        synchronized from the newer Redis state when available. REST is not queried here.
        """
        if self.state_store is None:
            return
        positions = {}
        for symbol, pos in self.state.positions.items():
            positions[symbol] = {
                "symbol": pos.symbol,
                "position_amt": str(pos.position_amt),
                "entry_price": str(pos.entry_price),
                "mark_price": str(pos.mark_price),
                "unrealized_pnl": str(pos.unrealized_pnl),
                "liquidation_price": str(pos.liquidation_price),
                "leverage": str(pos.leverage),
                "margin_type": pos.margin_type,
                "opened_at_ms": int(pos.opened_at_ms),
                "open_time_known": bool(pos.open_time_known),
            }
        current_source = str(self.state.account_snapshot.get("_source", "rest_bootstrap"))
        current_authoritative = bool(self.state.account_snapshot.get("_authoritative", False))
        payload = {
            "mode": self.execution_mode,
            "source": current_source,
            "authoritative": current_authoritative,
            "updated_at_ms": int(time.time() * 1000),
            "last_event_time_ms": int(self.state.last_event_time_ms),
            "last_state_source_priority": int(self.state._state_version[0]),
            "last_state_event_time_ms": int(self.state._state_version[1]),
            "last_user_stream_message_time_ms": int(self.state.last_user_stream_message_time_ms),
            "last_user_stream_transport_activity_time_ms": int(self.state.last_user_stream_transport_activity_time_ms),
            "last_account_state_update_time_ms": int(self.state.last_account_state_update_time_ms),
            "account": dict(self.state.account_snapshot),
            "positions": positions,
        }
        try:
            await self.state_store.set(self.state_key, json.dumps(payload, separators=(",", ":")))
        except Exception:
            log.exception("failed to publish authoritative account state to Redis")

    async def _hot_state_sync_loop(self) -> None:
        """Keep the local execution projection synchronized from shared Redis hot state."""
        if self.state_store is None or not hasattr(self.state_store, "get"):
            return
        while not self._stop.is_set():
            try:
                raw = await self.state_store.get(self.state_key)
                if raw:
                    payload = json.loads(raw) if isinstance(raw, str) else raw
                    self.state.apply_hot_state_payload(payload)
                await asyncio.sleep(self.hot_state_poll_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("shared account hot-state sync failed")
                await asyncio.sleep(max(self.hot_state_poll_seconds, 0.5))

    def account_observation(self, symbol: str, *, now_ms: int | None = None) -> list[float]:
        """Return the canonical normalized account observation for inference.

        Callers never choose how exchange state is adapted or normalized; the adapter
        owns the provider and its decision-time configuration.
        """
        return self._account_observation_provider.observation(symbol, now_ms=now_ms).tolist()

    async def _sync_hot_state_before_read(self) -> None:
        if self.state_store is None or not hasattr(self.state_store, "get"):
            return
        try:
            raw = await self.state_store.get(self.state_key)
            if raw:
                payload = json.loads(raw) if isinstance(raw, str) else raw
                self.state.apply_hot_state_payload(payload)
        except Exception:
            log.exception("failed to refresh account state from Redis hot state")

    async def account_observation_async(self, symbol: str, *, now_ms: int | None = None) -> list[float]:
        await self._sync_hot_state_before_read()
        return self._account_observation_provider.observation(symbol, now_ms=now_ms).tolist()

    async def account_snapshot_async(self, *, symbol: str, now_ms: int | None = None, require_fresh: bool = True) -> dict[str, Any]:
        await self._sync_hot_state_before_read()
        return self.account_snapshot(symbol=symbol, now_ms=now_ms, require_fresh=require_fresh)

    async def start(self):
        if self.rest.session is None:
            await self.rest.start()
        await self.rest.sync_server_time()
        # Bootstrap before websocket consumption to make reconciliation deterministic.
        await self.bootstrap_state()
        self._listen_key = await self.rest.create_listen_key()
        self._stop.clear()
        self._ws_task = asyncio.create_task(self._user_stream_loop(), name="binance-user-stream")
        self._keepalive_task = asyncio.create_task(self._keepalive_loop(), name="binance-listen-key-keepalive")
        self._health_task = asyncio.create_task(self._health_loop(), name="binance-user-stream-health")
        if self.state_store is not None and hasattr(self.state_store, "get"):
            self._hot_state_task = asyncio.create_task(self._hot_state_sync_loop(), name="account-hot-state-sync")
        if self.require_ws_for_trading:
            deadline = asyncio.get_running_loop().time() + self.ws_start_timeout_seconds
            while not self.ws_connected and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.1)
            if not self.ws_connected:
                await self.stop()
                raise ConnectionError("execution refused: authenticated user-data WebSocket did not become healthy")
        self._ready.set()

    async def stop(self):
        self._stop.set()
        for task in (self._ws_task, self._keepalive_task, self._health_task, self._hot_state_task):
            if task:
                task.cancel()
        for task in (self._ws_task, self._keepalive_task, self._health_task, self._hot_state_task):
            if task:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if self._listen_key:
            try:
                await self.rest.close_listen_key(self._listen_key)
            except Exception:
                log.exception("failed to close listen key")
        self._listen_key = None
        self._hot_state_task = None
        self.ws_connected = False
        self._ready.clear()

    async def bootstrap_state(self):
        account = await self.rest.account()
        self.state.account_snapshot=dict(account)
        self.state.account_snapshot["_equity"] = float(account.get("totalMarginBalance",account.get("totalWalletBalance",0)) or 0)
        self.state.account_snapshot["_source"] = "rest_bootstrap"
        self.state.account_snapshot["_authoritative"] = False
        bootstrap_now_ms = int(time.time() * 1000)
        self.state.account_snapshot["_bootstrap_time_ms"] = bootstrap_now_ms
        self.state.last_user_stream_transport_activity_time_ms = 0
        self.state.user_stream_connected = False
        self.state.user_stream_authenticated = False
        self.state._accept_state_version(source_priority=0, event_time_ms=bootstrap_now_ms, arrival_time_ms=bootstrap_now_ms)
        positions = await self.rest.position_risk()
        lifecycle = PositionLifecycleService(
            mode=self.execution_mode,
            store=self.db_logger,
            exchange_reconstructor=self._recover_position_opened_at_from_exchange,
        )
        for p in positions:
            symbol = str(p.get("symbol", ""))
            if symbol:
                qty_dec = Decimal(str(p.get("positionAmt", "0")))
                restored_opened = None
                restored_known = False
                if qty_dec != 0:
                    try:
                        recovered = await lifecycle.recover(
                            symbol, float(qty_dec), p.get("positionSide", "BOTH")
                        )
                        restored_opened = recovered.opened_at_ms
                        restored_known = recovered.known
                    except Exception:
                        # Lifecycle remains explicitly unknown on a failed recovery.
                        log.exception("position lifecycle recovery failed for %s", symbol)
                self.state.positions[symbol] = InternalPosition(
                    symbol=symbol,
                    position_amt=qty_dec,
                    entry_price=Decimal(str(p.get("entryPrice", "0"))),
                    mark_price=Decimal(str(p.get("markPrice", "0"))),
                    unrealized_pnl=Decimal(str(p.get("unRealizedProfit", "0"))),
                    liquidation_price=Decimal(str(p.get("liquidationPrice", "0"))),
                    isolated_wallet=Decimal(str(p.get("isolatedWallet", "0"))),
                    margin_type=str(p.get("marginType", "ISOLATED")),
                    leverage=Decimal(str(p.get("leverage", "1"))),
                    opened_at_ms=int(restored_opened or 0) if qty_dec != 0 else 0,
                    open_time_known=bool(restored_known) if qty_dec != 0 else False,
                )
        # Canonical RL equity definition across REST bootstrap and authenticated user stream:
        # wallet balance plus cached unrealized PnL. Do not switch semantics when the source changes.
        try:
            wallet_balance = float(account.get("totalWalletBalance", account.get("walletBalance", 0)) or 0.0)
            total_upnl = sum(float(pos.unrealized_pnl) for pos in self.state.positions.values())
            self.state.account_snapshot["_equity"] = wallet_balance + total_upnl
            self.state.account_snapshot["_equity_definition"] = "totalWalletBalance_plus_position_unrealized_pnl"
        except (TypeError, ValueError):
            pass
        await self._publish_authoritative_state()
    async def _recover_position_opened_at_from_exchange(
        self, symbol: str, current_qty: float, position_side: str = "BOTH", *, max_pages: int = 1000
    ) -> int | None:
        """Paginate Binance user trades until the current position's opening run is provable.

        Binance caps each user-trade response at 1000 rows. We walk backwards using
        ``endTime`` derived from the oldest returned trade, then reconstruct the full
        chronological position run locally. If the history still cannot prove the
        opening timestamp, ``None`` is returned rather than pretending it is ``0``.
        """
        target = float(current_qty or 0.0)
        if abs(target) < 1e-15:
            return None
        page_size = 1000
        end_time: int | None = None
        all_trades: list[dict[str, Any]] = []
        seen: set[tuple[int, int]] = set()
        history_exhausted = False
        for _ in range(max_pages):
            params: dict[str, Any] = {"limit": page_size}
            if end_time is not None:
                params["endTime"] = int(end_time)
            page = await self.rest.user_trades(symbol, **params)
            if not page:
                break
            normalized = [dict(t) for t in page]
            new_count = 0
            for trade in normalized:
                ts = int(trade.get("time", trade.get("T", 0)) or 0)
                tid = int(trade.get("id", 0) or 0)
                key = (ts, tid)
                if key not in seen:
                    seen.add(key)
                    all_trades.append(trade)
                    new_count += 1
            ordered = sorted(normalized, key=lambda x: (int(x.get("time", x.get("T", 0)) or 0), int(x.get("id", 0) or 0)))
            oldest_ts = int(ordered[0].get("time", ordered[0].get("T", 0)) or 0)
            if len(normalized) < page_size or oldest_ts <= 0:
                history_exhausted = True
                break
            next_end = oldest_ts - 1
            if end_time is not None and next_end >= end_time:
                break
            end_time = next_end
            if new_count == 0:
                break
        if not history_exhausted:
            # We hit the safety page limit without reaching the beginning of the
            # available history, so the opening timestamp cannot be proven.
            return None
        return reconstruct_opened_at_ms(all_trades, target, position_side=position_side)

        # Bootstrap open orders for all configured symbols is intentionally left to reconciliation;
        # this call is cheap for a single-symbol paper account and gives us an initial order map.
        for symbol in sorted({p.symbol for p in self.state.positions.values() if p.symbol}):
            try:
                for o in await self.rest.open_orders(symbol):
                    self.state.apply_order_update({"o": o, "E": o.get("updateTime", 0)})
            except Exception:
                log.exception("open-order bootstrap failed for %s", symbol)

    async def _user_stream_loop(self):
        import websockets
        delay = 1
        while not self._stop.is_set():
            if not self._listen_key:
                return
            url = self.rest.user_stream_url(self._listen_key)
            try:
                async with websockets.connect(url, ping_interval=None, ping_timeout=None, max_size=8 * 1024 * 1024) as ws:
                    self.ws_connected = True
                    self.state.user_stream_connected = True
                    self.state.user_stream_authenticated = True
                    self.state.note_user_stream_transport_activity()
                    if self._user_stream_recovery_pending:
                        recovered = await self._recover_account_state_after_user_stream_failure()
                        self._user_stream_recovery_pending = not recovered
                    heartbeat_task = asyncio.create_task(self._transport_heartbeat(ws), name="binance-user-stream-heartbeat")
                    if self.db_logger:
                        await self.db_logger.log_ws_health(True, last_event_time_ms=self.state.last_event_time_ms)
                    delay = 1
                    try:
                        async for raw in ws:
                            event = json.loads(raw)
                            await self._handle_user_event(event)
                            if self._stop.is_set():
                                return
                    finally:
                        heartbeat_task.cancel()
                        try:
                            await heartbeat_task
                        except asyncio.CancelledError:
                            pass
            except asyncio.CancelledError:
                raise
            except Exception:
                self.ws_connected = False
                self.state.user_stream_connected = False
                self.state.user_stream_authenticated = False
                self._user_stream_recovery_pending = True
                self.state.account_snapshot["_recovery_required"] = True
                self._last_ws_error_time = time.time()
                try:
                    from app.monitoring import observe_user_ws_reconnect
                    observe_user_ws_reconnect(self.execution_mode)
                except Exception: pass
                if self.db_logger:
                    await self.db_logger.log_ws_health(False, last_event_time_ms=self.state.last_event_time_ms, error="user-data websocket disconnected")
                log.exception("Binance user-data websocket disconnected; reconnecting")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

    async def _recover_account_state_after_user_stream_failure(self) -> bool:
        """Use REST once after a user-stream failure, never in inference.

        The authenticated stream remains the higher-authority source when it is
        available. This REST request is a post-disconnect reconciliation gate: it
        must complete before a pre-disconnect snapshot becomes eligible again.
        """
        try:
            await self.refresh_account_state()
        except Exception:
            log.exception("account REST recovery failed after user-stream disconnect")
            return False
        self.state.account_snapshot.pop("_recovery_required", None)
        return True

    async def _transport_heartbeat(self, ws) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(10)
            pong = await ws.ping()
            await pong
            self.state.note_user_stream_transport_activity()

    async def _handle_user_event(self, event):
        self.state.note_user_stream_message()
        kind = event.get("e")
        if kind == "ORDER_TRADE_UPDATE":
            self.state.apply_order_update(event)
            self.state.apply_trade_update(event)
        elif kind == "ACCOUNT_UPDATE":
            before={k:v.opened_at_ms for k,v in self.state.positions.items()}
            self.state.apply_account_update(event)
            if self.db_logger:
                for sym,pos in self.state.positions.items():
                    if pos.position_amt != 0 and before.get(sym,0)==0:
                        if pos.open_time_known and pos.opened_at_ms:
                            await self.db_logger.save_position_open_state(self.execution_mode, sym, pos.opened_at_ms, known=True)
                        else:
                            await self.db_logger.save_position_open_state(self.execution_mode, sym, None, known=False)
                    elif pos.position_amt == 0 and before.get(sym,0):
                        await self.db_logger.save_position_open_state(self.execution_mode, sym, None, known=False)
            await self._publish_authoritative_state()
        elif kind == "listenKeyExpired":
            self._listen_key = await self.rest.create_listen_key()
            raise ConnectionError("Binance listen key expired; reconnecting with a new key")
        elif kind == "MARGIN_CALL":
            log.warning("Binance margin call event: %s", event)
        if kind == "ORDER_TRADE_UPDATE":
            await self._publish_authoritative_state()
        for cb in self._event_callbacks:
            result = cb(event)
            if asyncio.iscoroutine(result):
                await result
        if self.db_logger:
            await self.db_logger.log_user_event(event)
            if kind == "ORDER_TRADE_UPDATE":
                await self.db_logger.log_order(event.get("o", {}), mode=self.execution_mode, latency_ms=0.0, request={"source": "user_stream"})
                if event.get("o", {}).get("x") == "TRADE" and Decimal(str(event.get("o", {}).get("l", "0"))) != 0:
                    await self.db_logger.log_fill(event.get("o", {}), mode=self.execution_mode)

    async def _health_loop(self):
        while not self._stop.is_set():
            try:
                if self.db_logger:
                    await self.db_logger.log_ws_health(
                        self.ws_connected,
                        last_event_time_ms=self.state.last_event_time_ms,
                        error=None if self.ws_connected else "user-data websocket disconnected",
                    )
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("failed to persist websocket health")
                await asyncio.sleep(5)

    async def _keepalive_loop(self):
        while not self._stop.is_set():
            try:
                await asyncio.sleep(30 * 60)
                if self._listen_key:
                    self._listen_key = await self.rest.keepalive_listen_key(self._listen_key)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("listen-key keepalive failed")

    async def refresh_account_state(self):
        """Reconcile via REST using the common monotonic source-version policy."""
        data = await self.rest.account()
        observed_at_ms = int(time.time() * 1000)
        self.state.account_snapshot["_last_reconcile_time_ms"] = observed_at_ms
        # Authenticated user-stream state has higher source authority than REST reconciliation.
        # Never replace it with a REST snapshot, even when the REST response was observed later.
        if bool(self.state.account_snapshot.get("_authoritative", False)) and self.state.account_snapshot.get("_source") == "authenticated_user_stream":
            return data
        accepted = self.state._accept_state_version(
            source_priority=10, event_time_ms=observed_at_ms, arrival_time_ms=observed_at_ms
        )
        if not accepted:
            return data
        self.state.account_snapshot = dict(data)
        wallet_balance = float(data.get("totalWalletBalance", data.get("walletBalance", 0)) or 0.0)
        total_upnl = sum(float(pos.unrealized_pnl) for pos in self.state.positions.values())
        self.state.account_snapshot["_equity"] = wallet_balance + total_upnl
        self.state.account_snapshot["_equity_definition"] = "totalWalletBalance_plus_position_unrealized_pnl"
        self.state.account_snapshot["_source"] = "rest_reconciliation"
        self.state.account_snapshot["_authoritative"] = False
        self.state.account_snapshot["_reconcile_time_ms"] = observed_at_ms
        return data

    def account_snapshot(self, *, symbol: str | None = None, now_ms: int | None = None, require_fresh: bool = True) -> dict[str, Any]:
        """Return account state only when it is safe for trading/risk decisions.

        During startup, REST bootstrap is accepted only after the authenticated user stream
        has connected. During steady state, user-stream state must remain fresh.
        """
        if require_fresh:
            check_symbol = symbol or ""
            self.state.account_snapshot_for(
                check_symbol, now_ms=now_ms,
                max_age_ms=self._user_stream_max_silence_ms if self.state.account_snapshot.get("_source") == "authenticated_user_stream" else self._bootstrap_max_age_ms,
                allow_bootstrap=True, ws_connected=self.ws_connected, require_user_stream_health=True,
                transport_max_age_ms=self._user_stream_transport_max_age_ms,
            )
        return dict(self.state.account_snapshot)

    async def submit(self, *, symbol: str, side: str, quantity: str | Decimal,
                     order_type: str = "MARKET", client_order_id: str | None = None,
                     reduce_only: bool = False, **params):
        if not self._ready.is_set():
            raise RuntimeError("paper execution adapter is not started")
        cid = client_order_id or f"paper_{uuid.uuid4().hex[:20]}"
        # Client order IDs are idempotency keys. A repeated intent returns the known
        # order rather than creating a duplicate exchange order.
        existing = self.state.orders.get(cid)
        if existing is not None:
            return existing.raw or {"clientOrderId": cid, "orderId": existing.exchange_order_id, "status": existing.status}
        request = {"symbol": symbol, "side": side, "type": order_type, "quantity": str(quantity),
                   "newClientOrderId": cid, "newOrderRespType": "RESULT"}
        if reduce_only:
            request["reduceOnly"] = "true"
        request.update(params)
        t0 = time.perf_counter_ns()
        try:
            response = await self.rest.new_order(**request)
        except Exception:
            self._rest_error_count += 1
            raise
        latency_ms = (time.perf_counter_ns() - t0) / 1e6
        self.state.apply_order_update({"o": response, "E": int(time.time() * 1000)})
        if self.db_logger:
            await self.db_logger.log_order(response, mode=self.execution_mode, latency_ms=latency_ms, request=request)
        return response

    async def cancel(self, symbol: str, *, order_id=None, orig_client_order_id=None):
        response = await self.rest.cancel_order(symbol, order_id=order_id, orig_client_order_id=orig_client_order_id)
        self.state.apply_order_update({"o": response, "E": int(time.time() * 1000)})
        if self.db_logger:
            await self.db_logger.log_order(response, mode=self.execution_mode, latency_ms=0.0, request={"cancel": True})
        return response


class PaperTradingEngine:
    """Policy -> observation -> RiskManager -> Binance Testnet execution loop."""
    def __init__(self, *, policy, observation_builder, execution: BinancePaperExecutionAdapter,
                 symbol: str, quantity: Decimal, interval_seconds: float = 1.0, risk_manager=None, capital_ramp=None, risk_event_logger=None, risk_context_provider=None):
        self.policy=policy; self.observation_builder=observation_builder; self.execution=execution
        self.symbol=symbol; self.quantity=Decimal(str(quantity)); self.interval_seconds=interval_seconds
        self.risk_manager=risk_manager
        self.capital_ramp=capital_ramp
        self.risk_event_logger=risk_event_logger
        self.risk_context_provider=risk_context_provider
        self._stop=asyncio.Event(); self.last_action=None; self._intent_seq=0; self.last_equity=None

    async def run(self):
        await self.execution.start()
        try:
            while not self._stop.is_set():
                obs=await self.observation_builder.get_observation()
                action=self.policy.predict(obs)
                await self._execute_action(action)
                await asyncio.sleep(self.interval_seconds)
        finally:
            await self.execution.stop()

    def stop(self): self._stop.set()
    async def execute_action(self, action): return await self._execute_action(action)

    async def _execute_action(self, action):
        action=int(action)
        pos=self.execution.state.positions.get(self.symbol, InternalPosition(self.symbol))
        signed_qty=Decimal(str(pos.position_amt)); mark=float(pos.mark_price or 0)
        decision=None
        if self.risk_manager:
            try:
                account=await self.execution.account_snapshot_async(symbol=self.symbol, require_fresh=True)
            except RuntimeError as exc:
                # Never make a risk/execution decision from stale account state. Freeze entries.
                self.last_equity = None
                if self.risk_manager:
                    self.risk_manager.observe(equity=None, ws_connected=False, rest_error=False)
                if self.risk_event_logger:
                    await self.risk_event_logger.log_risk_event(
                        RiskDecision(False, action, ["account_state_stale"], False),
                        mode=getattr(self.execution, "execution_mode", None),
                        metrics={"ws_connected": self.execution.ws_connected},
                    )
                raise RuntimeError("risk execution blocked: account state is stale or user stream is unhealthy") from exc
            try:
                equity=float(account.get("_equity", account.get("totalWalletBalance", 0)) or 0)
                self.last_equity=equity
            except (TypeError, ValueError):
                equity=None
            # BinanceREST invokes the risk error callback on every failed attempt; this observe is the
            # normal heartbeat and carries the latest account equity without masking REST failures.
            ctx={"short_vol":None,"rolling_vol_mean":None,"rolling_vol_std":None,"feature_values":None}
            if self.risk_context_provider:
                provided=self.risk_context_provider()
                if asyncio.iscoroutine(provided): provided=await provided
                if provided: ctx.update(provided)
            self.risk_manager.observe(equity=equity, ws_connected=self.execution.ws_connected, rest_error=False, **{k:ctx[k] for k in ("short_vol","rolling_vol_mean","rolling_vol_std","feature_values")})
            decision=self.risk_manager.check_action(action,position_qty=float(signed_qty),equity=float(equity or 0),mark_price=mark,leverage=float(pos.leverage or 1),concurrent_positions=sum(1 for p in self.execution.state.positions.values() if p.position_amt!=0), requested_qty=float(self.quantity), capital_ramp=self.capital_ramp)
            if self.risk_event_logger:
                short_vol, vol_mean, vol_std = self.risk_manager.volatility_stats()
                await self.risk_event_logger.log_risk_event(decision, metrics={"equity": equity, "mark_price": mark, "position_qty": float(signed_qty), "leverage": float(pos.leverage or 1), "short_vol": short_vol, "rolling_vol_mean": vol_mean, "rolling_vol_std": vol_std, "ws_connected": self.execution.ws_connected})
            if decision and not decision.allowed and observe_risk_veto:
                for reason in decision.reasons: observe_risk_veto(getattr(self.execution,'mode','UNKNOWN'), str(reason))
            action=decision.action
            if decision.flatten and signed_qty!=0:
                action=3
        self._intent_seq += 1
        intent=f"{self.symbol}:{self._intent_seq}:{action}"
        def cid(side,kind):
            return "p6_"+hashlib.sha256(f"{intent}:{side}:{kind}".encode()).hexdigest()[:24]
        if action==0 and signed_qty<=0:
            if signed_qty<0:
                await self.execution.submit(symbol=self.symbol,side="BUY",quantity=abs(signed_qty),reduce_only=True,client_order_id=cid("BUY","close-short"))
            await self.execution.submit(symbol=self.symbol,side="BUY",quantity=self.quantity,client_order_id=cid("BUY","open-long"))
        elif action==1 and signed_qty>=0:
            if signed_qty>0:
                await self.execution.submit(symbol=self.symbol,side="SELL",quantity=abs(signed_qty),reduce_only=True,client_order_id=cid("SELL","close-long"))
            await self.execution.submit(symbol=self.symbol,side="SELL",quantity=self.quantity,client_order_id=cid("SELL","open-short"))
        elif action in (2,3) and signed_qty!=0:
            await self.execution.submit(symbol=self.symbol,side="SELL" if signed_qty>0 else "BUY",quantity=abs(signed_qty),reduce_only=True,client_order_id=cid("CLOSE","close"))
        self.last_action=action
        return decision
