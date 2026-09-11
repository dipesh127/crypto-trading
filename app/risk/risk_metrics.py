from .tail import parametric_var, expected_shortfall
from .drift import rolling_sharpe, psi, kl_divergence

def tail_report(returns, alpha=0.99):
    return {"alpha": alpha, "parametric_var": parametric_var(returns,alpha), "expected_shortfall": expected_shortfall(returns,alpha)}
