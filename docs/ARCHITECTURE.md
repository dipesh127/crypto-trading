# Phase 1 architecture

```text
Binance REST ───────┐
                    ├──> ingestion -> validation -> TimescaleDB
Binance WebSocket ──┘                 └-> Redis hot state

REST depth snapshot + websocket depth diffs
                  |
                  v
          OrderBookReconciler
                  |
          contiguous local book
```

The data layer is observation-only. Execution, risk, portfolio accounting and RL are intentionally
excluded until their phases.