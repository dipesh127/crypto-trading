from __future__ import annotations
from .brackets import BracketTable


def isolated_liquidation_price(entry_price, qty, isolated_wallet_balance, brackets: BracketTable, side, fee_buffer: float = 0.0):
    """Calculate Binance USDⓈ-M isolated liquidation price piecewise by maintenance bracket.

    For a long: W + q(P-E) = q*P*MMR - CUM.
    For a short: W + q(E-P) = q*P*MMR - CUM.
    Therefore the candidate price is solved separately for every bracket and the candidate whose
    notional falls inside that bracket is selected. This uses Binance's cumulative maintenance
    amount (``cum``), not a single global maintenance rate approximation.
    """
    q=abs(float(qty)); e=float(entry_price); w=float(isolated_wallet_balance); s=1 if float(side)>0 else -1
    if q <= 0 or e <= 0 or w < 0: raise ValueError("entry_price/qty must be positive and wallet balance non-negative")
    # Optional explicit fee buffer is deducted from available isolated wallet balance.
    w=max(0.0,w-float(fee_buffer))
    for b in brackets.rows:
        den=q*(s-b.maint_margin_ratio)
        if abs(den)<1e-15: continue
        p=(s*q*e-w-b.cum)/den
        if p>0 and b.notional_floor <= q*p <= b.notional_cap:
            return float(p)
    # If a candidate lies exactly at a bracket boundary, Binance's piecewise function is
    # continuous when cum is correct. Use the entry notional tier as a deterministic fallback.
    b=brackets.for_notional(q*e); den=q*(s-b.maint_margin_ratio)
    if abs(den)<1e-15: return float("nan")
    return float((s*q*e-w-b.cum)/den)


def liquidation_trigger(mark_price, entry_price, qty, isolated_wallet_balance, brackets, side):
    p=isolated_liquidation_price(entry_price,qty,isolated_wallet_balance,brackets,side)
    return (side>0 and mark_price<=p) or (side<0 and mark_price>=p),p
