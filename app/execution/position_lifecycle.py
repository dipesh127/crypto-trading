"""Persistent opening-time recovery for currently open exchange positions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass(frozen=True)
class PositionLifecycle:
    opened_at_ms: int | None
    known: bool
    source: str


class PositionLifecycleService:
    """Resolve a live position's lifecycle from durable and exchange evidence.

    Resolution order is intentional: persisted lifecycle state, durable local fill
    history, then Binance execution history.  A non-flat position without evidence
    is returned as explicitly unknown; it is never assigned a synthetic zero time.
    """

    def __init__(self, *, mode: str, store: Any = None,
                 exchange_reconstructor: Callable[[str, float, str], Awaitable[int | None]] | None = None):
        self.mode = mode
        self.store = store
        self.exchange_reconstructor = exchange_reconstructor

    async def recover(self, symbol: str, current_qty: float, position_side: str = "BOTH") -> PositionLifecycle:
        if abs(float(current_qty or 0.0)) < 1e-15:
            return PositionLifecycle(None, False, "flat")

        if self.store is not None:
            try:
                opened_at, known = await self.store.load_position_open_state(self.mode, symbol)
                if known and opened_at and int(opened_at) > 0:
                    return PositionLifecycle(int(opened_at), True, "local_lifecycle")

                opened_at = await self.store.reconstruct_position_opened_at(
                    self.mode, symbol, float(current_qty), position_side
                )
                if opened_at and int(opened_at) > 0:
                    await self.store.save_position_opened_at(self.mode, symbol, int(opened_at))
                    return PositionLifecycle(int(opened_at), True, "local_execution_history")
            except Exception:
                # A local journal outage must not prevent exchange-history recovery.
                pass

        if self.exchange_reconstructor is not None:
            try:
                opened_at = await self.exchange_reconstructor(symbol, float(current_qty), position_side)
                if opened_at and int(opened_at) > 0:
                    if self.store is not None:
                        await self.store.save_position_opened_at(self.mode, symbol, int(opened_at))
                    return PositionLifecycle(int(opened_at), True, "exchange_execution_history")
            except Exception:
                # Preserve the explicit-unknown state below if the exchange is down.
                pass

        if self.store is not None:
            await self.store.save_position_open_state(self.mode, symbol, None, known=False)
        return PositionLifecycle(None, False, "unknown")
