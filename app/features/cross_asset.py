from __future__ import annotations
import numpy as np
import pandas as pd


def _series(frame, name='close'):
    if name not in frame:
        raise ValueError(f"cross-asset frame missing '{name}'")
    s = pd.to_numeric(frame[name], errors='coerce').sort_index()
    return s[~s.index.duplicated(keep='last')]


def btc_correlation(close: pd.Series, btc_close: pd.Series, window: int = 60) -> pd.Series:
    """Rolling Pearson correlation of asset and BTC log returns."""
    a = np.log(_series(pd.DataFrame({'close': close}))).diff()
    b = np.log(_series(pd.DataFrame({'close': btc_close}))).diff()
    a, b = a.align(b, join='left')
    return a.rolling(window, min_periods=max(10, window // 2)).corr(b)


def btc_beta(close: pd.Series, btc_close: pd.Series, window: int = 60) -> pd.Series:
    """Rolling beta = Cov(asset,BTC) / Var(BTC)."""
    a = np.log(_series(pd.DataFrame({'close': close}))).diff()
    b = np.log(_series(pd.DataFrame({'close': btc_close}))).diff()
    a, b = a.align(b, join='left')
    cov = a.rolling(window, min_periods=max(10, window // 2)).cov(b)
    var = b.rolling(window, min_periods=max(10, window // 2)).var()
    return cov / var.replace(0, np.nan)


def _rank_percentile(series_by_symbol: dict[str, pd.Series]) -> pd.DataFrame:
    frame = pd.concat(series_by_symbol, axis=1).sort_index()
    # Cross-sectional percentile rank at each timestamp. Values with insufficient data stay NaN.
    return frame.rank(axis=1, pct=True, method='average')


def cross_sectional_features(frames: dict[str, pd.DataFrame], window: int = 20) -> dict[str, pd.DataFrame]:
    """Compute leakage-safe cross-sectional ranks for returns, momentum, volatility and volume.

    Each rank is computed independently at a timestamp from only observations available at that
    timestamp. Missing symbols are excluded from the ranking rather than forward-filled.
    """
    closes = {s: _series(df) for s, df in frames.items()}
    volumes = {s: _series(df, 'volume') for s, df in frames.items() if 'volume' in df}
    returns = {s: np.log(v).diff() for s, v in closes.items()}
    momentum = {s: v.pct_change(window) for s, v in closes.items()}
    volatility = {s: r.rolling(window, min_periods=max(5, window // 2)).std() for s, r in returns.items()}
    volume_momentum = {s: v.pct_change(window) for s, v in volumes.items()}
    return {
        'return_rank': _rank_percentile(returns),
        'momentum_rank': _rank_percentile(momentum),
        'volatility_rank': _rank_percentile(volatility),
        'volume_rank': _rank_percentile(volume_momentum),
    }
