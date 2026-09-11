from __future__ import annotations
from collections.abc import Mapping
from pathlib import Path
import json
import inspect
import numpy as np

from .account_state import AccountObservationBuilder, AccountSnapshot

class TrainedPolicy:
    """Single inference facade used by paper and future live execution paths."""
    def __init__(self, model):
        self.model = model

    @classmethod
    def load(cls, model_path):
        from stable_baselines3 import PPO, SAC
        path = str(model_path)
        # Try PPO first because Phase 4's default policy is PPO; fall back to SAC.
        try:
            return cls(PPO.load(path))
        except Exception as ppo_error:
            try:
                return cls(SAC.load(path))
            except Exception:
                raise RuntimeError(f"Could not load PPO or SAC checkpoint: {model_path}") from ppo_error


    @classmethod
    def load_ensemble(cls, model_paths, algorithm='ppo', weights=None):
        from .ensemble import EnsemblePolicy
        return cls(EnsemblePolicy.load(model_paths,weights=weights,algorithm=algorithm))
    def predict(self, observation, deterministic=True):
        action, _ = self.model.predict(observation, deterministic=deterministic)
        if isinstance(action, np.ndarray):
            return int(action.reshape(-1)[0]) if action.size == 1 and np.issubdtype(action.dtype, np.integer) else action
        return action


class LiveFeatureObservationBuilder:
    """Adapter for the exact observation shape used by CryptoFuturesEnv.

    The production market-data collector supplies a feature DataFrame. This builder does not
    refit scalers or alter the feature list; it uses the checkpoint manifest to enforce schema.
    """
    def __init__(
        self,
        feature_frame_provider,
        feature_columns,
        window=60,
        account_snapshot_provider=None,
        *,
        account_provider=None,
        account_decision_interval_seconds=60.0,
        account_observation_builder=None,
    ):
        self.provider = feature_frame_provider
        self.feature_columns = list(feature_columns)
        self.window = int(window)
        # ``account_provider`` remains a compatibility alias, but it now supplies
        # raw AccountSnapshot/mapping state rather than a hand-built RL vector.
        if account_snapshot_provider is not None and account_provider is not None:
            raise ValueError("provide only one account snapshot provider")
        self.account_snapshot_provider = account_snapshot_provider or account_provider
        if self.account_snapshot_provider is None:
            raise ValueError("live inference requires an account snapshot provider")
        self.account_observation_builder = account_observation_builder or AccountObservationBuilder(
            window_bars=self.window,
            bar_seconds=account_decision_interval_seconds,
        )

    async def _account_observation(self) -> np.ndarray:
        snapshot = self.account_snapshot_provider()
        if inspect.isawaitable(snapshot):
            snapshot = await snapshot
        if isinstance(snapshot, (list, tuple, np.ndarray)):
            raise TypeError(
                "account snapshot provider must return AccountSnapshot or a raw mapping; "
                "prebuilt account observation vectors are not allowed"
            )
        if not isinstance(snapshot, AccountSnapshot) and not isinstance(snapshot, Mapping):
            raise TypeError("account snapshot provider must return AccountSnapshot or a raw mapping")
        return self.account_observation_builder.build(snapshot)

    async def get_observation(self):
        frame = self.provider()
        if hasattr(frame, "__await__"):
            frame = await frame
        missing = set(self.feature_columns) - set(frame.columns)
        if missing:
            raise ValueError(f"live feature frame missing checkpoint features: {sorted(missing)}")
        if len(frame) < self.window:
            raise RuntimeError(f"need {self.window} complete feature rows; got {len(frame)}")
        x = frame.iloc[-self.window:][self.feature_columns].to_numpy(dtype=np.float32)
        x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
        account = await self._account_observation()
        return {"market": x, "account": account}
