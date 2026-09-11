from __future__ import annotations

from typing import Any, Iterable, Mapping


def _signed_trade_qty(trade: Mapping[str, Any], position_side: str = "BOTH") -> float:
    qty = abs(float(trade.get("qty", trade.get("q", 0)) or 0))
    side = str(trade.get("side", trade.get("S", "")) or "").upper()
    signed = qty if side == "BUY" else -qty if side == "SELL" else 0.0
    if str(position_side or "BOTH").upper() == "SHORT":
        signed = -signed
    return signed


def reconstruct_opened_at_ms(
    trades: Iterable[Mapping[str, Any]],
    current_qty: float,
    *,
    position_side: str = "BOTH",
) -> int | None:
    """Return the start time of the currently-open position run.

    Trades are processed chronologically. Partial adds do not reset the opening
    timestamp; a zero crossing/reversal starts a new position run. Returns None when
    the supplied trade history cannot prove the current position's opening time.
    """
    target = float(current_qty or 0.0)
    if abs(target) < 1e-15:
        return None

    ps = str(position_side or "BOTH").upper()
    target_sign = 1 if target > 0 else -1
    ordered = sorted(
        trades or [],
        key=lambda x: (int(x.get("time", x.get("T", 0)) or 0), int(x.get("id", 0) or 0)),
    )
    net = 0.0
    opened_at = 0

    for trade in ordered:
        trade_ps = str(trade.get("positionSide", trade.get("ps", ps)) or ps).upper()
        if ps != "BOTH" and trade_ps not in {ps, "BOTH", ""}:
            continue

        signed = _signed_trade_qty(trade, ps)
        if signed == 0:
            continue
        previous = net
        net += signed
        ts = int(trade.get("time", trade.get("T", 0)) or 0)

        if (previous == 0.0 and net != 0.0) or (previous * net < 0.0):
            opened_at = ts
        elif opened_at == 0 and net != 0.0:
            opened_at = ts

    if net != 0.0 and (1 if net > 0 else -1) == target_sign and opened_at:
        return opened_at
    return None
