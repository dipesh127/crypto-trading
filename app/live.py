from __future__ import annotations
import asyncio
from .paper import BinancePaperExecutionAdapter


class BinanceLiveExecutionAdapter(BinancePaperExecutionAdapter):
    """Production adapter using the exact Phase-5 execution/state path.

    The class intentionally reuses the same order submission, user-data stream,
    reconciliation state and idempotency implementation. Live authorization is
    performed before construction/startup by app.golive.authorize_live().
    """
    def __init__(self, rest, *, db_logger=None, require_ws=True, ws_start_timeout=15.0, state_store=None, state_key=None, account_window_bars=60, account_decision_interval_seconds=60.0, account_max_age_ms=5000):
        super().__init__(rest, testnet_only=False, allow_live=True, db_logger=db_logger, execution_mode="LIVE", state_store=state_store, state_key=state_key, account_window_bars=account_window_bars, account_decision_interval_seconds=account_decision_interval_seconds, account_max_age_ms=account_max_age_ms)
        self.require_ws = require_ws
        self.ws_start_timeout = float(ws_start_timeout)

    async def start(self):
        await super().start()
        if self.require_ws:
            deadline = asyncio.get_running_loop().time() + self.ws_start_timeout
            while not self.ws_connected and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.1)
            if not self.ws_connected:
                await super().stop()
                raise ConnectionError("LIVE execution refused: authenticated user-data WebSocket did not become healthy")
