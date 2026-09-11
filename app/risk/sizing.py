from __future__ import annotations

def fixed_fractional_size(equity: float, risk_fraction: float, stop_distance: float) -> float:
    if equity < 0 or risk_fraction < 0 or stop_distance <= 0:
        raise ValueError("equity/risk_fraction must be non-negative and stop_distance positive")
    return equity * risk_fraction / stop_distance

def fractional_kelly_size(equity: float, win_probability: float, payoff_ratio: float, fraction: float = 0.5) -> float:
    if not 0 <= win_probability <= 1 or payoff_ratio <= 0 or not 0 < fraction <= 1:
        raise ValueError("invalid Kelly parameters")
    q = 1.0 - win_probability
    full = (payoff_ratio * win_probability - q) / payoff_ratio
    return max(0.0, equity * fraction * full)

def atr_position_size(equity: float, risk_fraction: float, atr: float, stop_multiplier: float) -> float:
    if equity < 0 or risk_fraction < 0 or atr <= 0 or stop_multiplier <= 0:
        raise ValueError("invalid ATR sizing parameters")
    return (equity * risk_fraction) / (atr * stop_multiplier)
