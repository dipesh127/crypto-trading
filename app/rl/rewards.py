from __future__ import annotations
from dataclasses import dataclass
import math

@dataclass
class DifferentialSharpe:
    eta: float = 0.01
    A: float = 0.0
    B: float = 0.0
    initialized: bool = False

    def reset(self):
        self.A = self.B = 0.0
        self.initialized = False

    def update(self, r: float) -> float:
        # Exponentially smoothed A=E[r], B=E[r^2].
        old_a, old_b = self.A, self.B
        if not self.initialized:
            self.A = self.eta * r
            self.B = self.eta * r * r
            self.initialized = True
            return 0.0
        dA = r - old_a
        dB = r * r - old_b
        denom = max(old_b - old_a * old_a, 1e-12)
        ds = (old_b * dA - 0.5 * old_a * dB) / (denom ** 1.5)
        self.A = (1.0 - self.eta) * old_a + self.eta * r
        self.B = (1.0 - self.eta) * old_b + self.eta * r * r
        return float(ds)


def shaped_reward(pnl: float, delta_position: float, commission_rate: float,
                   slippage_estimate: float, drawdown: float, previous_drawdown: float,
                   lambda_cost: float = 1.0, lambda_dd: float = 1.0) -> float:
    cost = lambda_cost * abs(delta_position) * (commission_rate + abs(slippage_estimate))
    dd_penalty = lambda_dd * max(0.0, drawdown - previous_drawdown)
    return float(pnl - cost - dd_penalty)
