# Phase 4 — RL Environment and Training

## Environment
`CryptoFuturesEnv` is Gymnasium-compatible and exposes a Dict observation:
- `market`: last 60 bars of engineered features
- `account`: position, normalized unrealized PnL, leverage, margin ratio, normalized time-in-position

Discrete actions: Long, Short, Flat, Close. `ContinuousCryptoFuturesEnv` exposes position sizing in [-1,1].

## Rewards
`shaped` implements transaction-cost + drawdown-aware shaping. `differential_sharpe` implements the Moody-Saffell-style differential Sharpe update with exponentially smoothed A/B.

## Policy
A shared TCN processes the market window. Account state is encoded separately and concatenated after temporal pooling. SB3 supplies separate policy/value heads for PPO and twin Q critics for SAC. PPO uses orthogonal initialization, GAE and clipped objective defaults; SAC is available for continuous actions.

## Training
Use vectorized DummyVecEnv/SubprocVecEnv. Training environments apply light randomization to fee/slippage assumptions. Chronological regime and walk-forward helpers are included. Optuna search space covers learning rate, gamma, GAE lambda, clip range, entropy coefficient, and reward coefficients.

## Reproducibility
Every saved model gets a metadata JSON containing training data window, feature version, feature columns, hyperparameters, backtest metrics and git commit. Pair this with Phase 2's feature-code SHA256/schema manifest for exact inference reproducibility.

## Champion/challenger
`ChampionRegistry` registers a challenger in shadow status, promotes after external paper/shadow validation, and supports one-command rollback.

## Install/run
```bash
python -m pip install -e ".[dev]"
python scripts/train_rl.py --data data/features.csv --features log_return_1m,ema_1m,rsi_1m,log_return_5m,rsi_5m --algorithm ppo --timesteps 100000 --envs 4
python scripts/promotion.py status
python scripts/promotion.py promote
python scripts/promotion.py rollback
```

## Purged/embargoed Optuna search

`app.rl.optuna_search.optimize_ppo()` now executes real PPO trials. Every trial samples the PPO/reward
hyperparameters, trains a model on every chronological purged/embargo fold, evaluates the held-out
validation partition, reports intermediate fold scores to Optuna for pruning, and returns the mean
validation Sharpe as the optimization objective. Use `scripts/optuna_search.py` for a CLI entry point.

Each training run logs parameters, final evaluation metrics, the model archive, an equity curve and a
metrics JSON to MLflow when MLflow is configured; without MLflow, the same files remain in the artifact
directory. The feature pipeline also exposes regime, BTC correlation/beta, and cross-sectional rank
features while preserving the training/live separation through `fit_regime()` and `fit_regime=False`.

## Inference ensemble
`app.rl.ensemble.EnsemblePolicy` supports weighted voting for discrete PPO actions and weighted averaging for continuous SAC actions. Paper/live runners accept `--ensemble-models`.
