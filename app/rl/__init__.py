from .walkforward import walkforward_windows, chronological_regime_windows, purged_embargo_splits
from .ensemble import EnsemblePolicy, EnsembleMember


# Keep the runtime account-state package usable when optional tuning dependencies
# are unavailable. Optuna is only needed by callers that launch a search.
def suggest_ppo(*args, **kwargs):
    from .optuna_search import suggest_ppo as implementation
    return implementation(*args, **kwargs)


def make_study(*args, **kwargs):
    from .optuna_search import make_study as implementation
    return implementation(*args, **kwargs)


def optimize_ppo(*args, **kwargs):
    from .optuna_search import optimize_ppo as implementation
    return implementation(*args, **kwargs)
