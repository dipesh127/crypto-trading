from __future__ import annotations
from dataclasses import dataclass
import numpy as np

@dataclass
class SharpeDecayResult:
    live_sharpe: float
    baseline_sharpe: float
    decay_fraction: float
    breached: bool

def sharpe_decay(live_sharpe, baseline_sharpe, max_decay_fraction=0.50):
    if live_sharpe is None or baseline_sharpe is None or not np.isfinite(live_sharpe) or not np.isfinite(baseline_sharpe):
        return SharpeDecayResult(float('nan'),float('nan'),float('nan'),False)
    if baseline_sharpe<=0:
        decay=0.0 if live_sharpe>=baseline_sharpe else 1.0
    else: decay=max(0.0,1.0-live_sharpe/baseline_sharpe)
    return SharpeDecayResult(float(live_sharpe),float(baseline_sharpe),float(decay),bool(decay>=max_decay_fraction))

def annualized_sharpe(returns, periods_per_year=252.0):
    x=np.asarray(list(returns),dtype=float); x=x[np.isfinite(x)]
    return float(np.sqrt(periods_per_year)*x.mean()/x.std(ddof=1)) if len(x)>1 and x.std(ddof=1)>0 else float('nan')
