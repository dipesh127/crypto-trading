# Phase 2 validation and semantics

## Exact implementation contract
- RSI/ATR/ADX: Wilder recursive smoothing (`alpha=1/n`, `adjust=False`).
- Bollinger: sample standard deviation (`ddof=1`).
- CVD: cumulative `(2 * taker_buy_base_volume - volume)`.
- OBI: `(bid_qty - ask_qty)/(bid_qty + ask_qty)`.
- Microprice: `(ask_price * bid_qty + bid_price * ask_qty)/(bid_qty + ask_qty)`.
- OFI: level-1 Cont-Kukanov-Stoikov event contribution, `OFI = e_bid - e_ask`.
- Kyle lambda: rolling covariance of price change and signed volume divided by rolling signed-volume variance.
- Hurst: rolling R/S estimate.
- Regime: KMeans or GMM on volatility/trend-strength/volume features; cluster IDs are remapped by training-set mean trend return.

## Leakage rules
1. Train-only scaler fitting.
2. Train-only regime fitting.
3. No backward time shifts in model features.
4. Multi-timeframe frames are computed separately; alignment must use information available at the decision timestamp.
5. Every checkpoint stores `feature_code_version`, `feature_code_sha256`, `schema_hash`, feature columns and scaler state.

## Reference tests
`tests/test_features.py` contains deterministic reference-value checks for the indicator families and integration checks for multi-timeframe and regime features.

## Extended features
- CMF (Chaikin Money Flow)
- depth-within-1/5/10/25/50-bps and depth imbalance
- causal exponentially decayed trade intensity (Hawkes-style)
- rolling ADF tau statistic
- rolling return autocorrelation (lag 1 and 5)
- BTC rolling correlation/beta
- cross-sectional return/momentum/volatility/volume ranks
