from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

@dataclass
class Mismatch:
    kind: str
    symbol: str | None
    expected: Any
    actual: Any
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self):
        return {"kind": self.kind, "symbol": self.symbol, "expected": self.expected, "actual": self.actual, "details": self.details}

class Reconciler:
    def __init__(self, execution, *, qty_tolerance=Decimal("0.00000001"), price_tolerance=Decimal("0.01"), db_logger=None, alert=None):
        self.execution = execution
        self.qty_tolerance = Decimal(str(qty_tolerance))
        self.price_tolerance = Decimal(str(price_tolerance))
        self.db_logger = db_logger
        self.alert = alert

    async def check(self, symbols: list[str] | None = None):
        symbols = [s.upper() for s in (symbols or [])]
        positions = await self.execution.rest.position_risk()
        exchange_positions = {str(x["symbol"]): x for x in positions if str(x.get("symbol", "")) in symbols or not symbols}
        mismatches: list[Mismatch] = []
        local_symbols = set(exchange_positions) | set(self.execution.state.positions)
        for symbol in local_symbols:
            lp = self.execution.state.positions.get(symbol)
            ep = exchange_positions.get(symbol)
            local_qty = lp.position_amt if lp else Decimal("0")
            actual_qty = Decimal(str(ep.get("positionAmt", "0"))) if ep else Decimal("0")
            if abs(local_qty - actual_qty) > self.qty_tolerance:
                mismatches.append(Mismatch("POSITION_QTY", symbol, str(local_qty), str(actual_qty)))
            if lp and ep:
                actual_entry = Decimal(str(ep.get("entryPrice", "0")))
                if abs(lp.entry_price - actual_entry) > self.price_tolerance and abs(actual_qty) > self.qty_tolerance:
                    mismatches.append(Mismatch("POSITION_ENTRY_PRICE", symbol, str(lp.entry_price), str(actual_entry)))
        for symbol in symbols:
            exchange_orders = await self.execution.rest.open_orders(symbol)
            actual = {str(o.get("clientOrderId")): o for o in exchange_orders}
            local = {cid: o for cid, o in self.execution.state.orders.items() if o.symbol == symbol and o.status in {"NEW", "PARTIALLY_FILLED"}}
            if set(local) != set(actual):
                mismatches.append(Mismatch("OPEN_ORDER_SET", symbol, sorted(local), sorted(actual)))
        result = {"ok": not mismatches, "mismatches": [m.as_dict() for m in mismatches]}
        self.execution.state.last_reconcile = result
        if self.db_logger:
            await self.db_logger.log_reconciliation(result)
        if mismatches and self.alert:
            r = self.alert(result)
            if hasattr(r, "__await__"):
                await r
        return result

    async def run(self, symbols, interval_seconds=30.0, stop_event=None):
        import asyncio
        stop_event = stop_event or asyncio.Event()
        while not stop_event.is_set():
            try:
                await self.check(symbols)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                result = {"ok": False, "error": repr(exc)}
                if self.db_logger:
                    await self.db_logger.log_reconciliation(result)
                if self.alert:
                    r = self.alert(result)
                    if hasattr(r, "__await__"):
                        await r
            await asyncio.sleep(interval_seconds)
