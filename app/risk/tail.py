from __future__ import annotations
import math
import numpy as np
from scipy.stats import norm

def parametric_var(returns, alpha: float = 0.99) -> float:
    x=np.asarray(returns,dtype=float); x=x[np.isfinite(x)]
    if x.size < 2 or not 0 < alpha < 1: raise ValueError("need >=2 returns and alpha in (0,1)")
    # Loss convention: positive number is a loss threshold.
    return float(-(x.mean() + norm.ppf(1-alpha)*x.std(ddof=1)))

def expected_shortfall(returns, alpha: float = 0.99) -> float:
    x=np.asarray(returns,dtype=float); x=x[np.isfinite(x)]
    if x.size < 2 or not 0 < alpha < 1: raise ValueError("need >=2 returns and alpha in (0,1)")
    losses=-x; threshold=float(np.quantile(losses, alpha, method="linear"))
    tail=losses[losses >= threshold]
    return float(tail.mean()) if tail.size else threshold
