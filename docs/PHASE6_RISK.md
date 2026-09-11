# PHASE 6 — Risk Management Layer

Risk is a policy-independent veto layer. It must run for paper and live-capital paths and fail closed if its state is unavailable.

## Controls
- Daily equity loss kill switch. Entry actions are vetoed and an open position can be flattened.
- Maximum leverage, position notional/equity cap, and concurrent-position cap.
- Realized-volatility circuit breaker: short-term volatility > rolling mean + N standard deviations pauses new entries without forcing a liquidation.
- Sustained user-data WebSocket disconnect and REST error-spike detection. Configurable flatten/freeze behavior.
- Deterministic `clientOrderId` values plus exchange-state deduplication prevent duplicate submission for the same intent.

## Sizing
- Fixed fractional: `equity * risk_fraction / stop_distance`.
- Fractional Kelly: `f=(b*p-q)/b`, scaled by a configurable 0.25–0.50 default range.
- ATR: `(equity*risk_fraction)/(ATR*stop_multiplier)`.

## Tail risk
Parametric VaR uses the normal-return convention in the phase specification and Expected Shortfall averages losses beyond the empirical alpha threshold.

## Drift
Rolling Sharpe decay and feature-distribution PSI/KL are calculated from live observations against the training distribution. A configured breach pauses new entries and records a review flag. Pause clearing requires explicit human review.

## Promotion
`PromotionChecklist` requires minimum profitable paper weeks, minimum trades, maximum drawdown and human sign-off. No automatic path promotes to real capital. `CapitalRamp` begins at 10% of approved target allocation and advances in 25/50/75/100% stages only after a minimum dwell period, positive PnL and drawdown checks.

## Integration
`PaperTradingEngine` invokes the risk manager after policy inference and before order submission. The risk manager may replace Long/Short with Close. Risk events should be persisted in `execution.risk_events` by the production DB adapter.
