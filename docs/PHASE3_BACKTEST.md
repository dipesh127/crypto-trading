# Phase 3 — Simulation / Backtest Engine

The simulator is an event-bar historical replay foundation. It supports market, limit, stop-market,
stop-limit, take-profit-market and trailing-stop-market orders, fee/slippage models, funding, bracket-based
isolated liquidation, performance metrics, Monte Carlo trade resampling, Newey-West tests, chronological
walk-forward splits and purged/embargoed folds.

Binance USDⓈ-M standard USDT fee defaults are encoded by VIP tier and are configurable. The default is
Regular/VIP 0: 0.0200% maker / 0.0500% taker.

Leverage brackets must be supplied from Binance `/fapi/v1/leverageBracket` and are never approximated.

For production fidelity, feed mark-price and funding observations from the Phase 1/2 data store rather than
using close prices as substitutes. The engine intentionally keeps these inputs explicit.
