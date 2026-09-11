from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

import numpy as np


ACCOUNT_OBSERVATION_NAMES = (
    "signed_exposure_fraction",
    "unrealized_pnl_fraction",
    "leverage",
    "equity_to_initial_margin",
    "time_in_position_fraction",
)


@dataclass(frozen=True)
class PositionSnapshot:
    """Raw state for one exchange position.

    ``position_qty`` is a base-asset quantity, never an RL target exposure.
    """

    position_qty: float = 0.0
    mark_price: float = 0.0
    unrealized_pnl: float = 0.0
    leverage: float = 1.0
    time_in_position_seconds: float = 0.0
    open_time_known: bool = True


@dataclass(frozen=True)
class AccountSnapshot:
    """Canonical raw account state consumed by the RL observation builder.

    All values are expressed in native exchange/account units. Normalization happens
    exactly once inside :class:`AccountObservationBuilder` so training, paper and live
    inference cannot silently implement different account-feature semantics.
    """

    position_qty: float = 0.0
    mark_price: float = 0.0
    unrealized_pnl: float = 0.0
    leverage: float = 1.0
    equity: float = 0.0
    maintenance_margin: float = 0.0
    time_in_position_seconds: float = 0.0
    open_time_known: bool = True
    # Last to preserve the original positional constructor for callers/tests.
    position: PositionSnapshot | None = None

    @property
    def position_snapshot(self) -> PositionSnapshot:
        """Use explicit position state while supporting legacy flat snapshots."""
        return self.position or PositionSnapshot(
            position_qty=self.position_qty,
            mark_price=self.mark_price,
            unrealized_pnl=self.unrealized_pnl,
            leverage=self.leverage,
            time_in_position_seconds=self.time_in_position_seconds,
            open_time_known=self.open_time_known,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AccountSnapshot":
        """Build from a provider-neutral mapping.

        Accepted aliases cover Binance REST/user-stream field names and the internal
        state names used by the historical environment.
        """

        def _float(*keys: str, default: float = 0.0) -> float:
            for key in keys:
                if key in value and value[key] is not None:
                    try:
                        return float(value[key])
                    except (TypeError, ValueError):
                        continue
            return float(default)

        position = PositionSnapshot(
            position_qty=_float("position_qty", "positionAmt", "position_amt", "pa"),
            mark_price=_float("mark_price", "markPrice", "mp"),
            unrealized_pnl=_float("unrealized_pnl", "unRealizedProfit", "up"),
            leverage=_float("leverage", "l", default=1.0),
            time_in_position_seconds=_float(
                "time_in_position_seconds", "time_in_position", "time_in_position_sec", default=0.0
            ),
            open_time_known=bool(value.get("open_time_known", value.get("position_open_time_known", True))),
        )
        return cls(
            position_qty=position.position_qty,
            mark_price=position.mark_price,
            unrealized_pnl=position.unrealized_pnl,
            leverage=position.leverage,
            equity=_float("equity", "_equity", "totalMarginBalance", "totalWalletBalance"),
            maintenance_margin=_float("maintenance_margin", "totalMaintMargin"),
            time_in_position_seconds=position.time_in_position_seconds,
            open_time_known=position.open_time_known,
            position=position,
        )


class AccountObservationBuilder:
    """Single source of truth for the five RL account-state features."""

    def __init__(self, *, window_bars: int = 60, bar_seconds: float = 60.0):
        if int(window_bars) <= 0:
            raise ValueError("window_bars must be positive")
        if float(bar_seconds) <= 0:
            raise ValueError("bar_seconds must be positive")
        self.window_bars = int(window_bars)
        self.bar_seconds = float(bar_seconds)

    @property
    def observation_names(self) -> tuple[str, ...]:
        return ACCOUNT_OBSERVATION_NAMES

    @property
    def time_window_seconds(self) -> float:
        return max(self.window_bars * self.bar_seconds, 1e-9)

    def build(self, snapshot: AccountSnapshot | Mapping[str, Any]) -> np.ndarray:
        if not isinstance(snapshot, AccountSnapshot):
            snapshot = AccountSnapshot.from_mapping(snapshot)

        equity = max(float(snapshot.equity), 1e-9)
        position = snapshot.position_snapshot
        leverage = max(float(position.leverage), 1e-9)
        mark = abs(float(position.mark_price))
        qty = float(position.position_qty)
        notional = abs(qty) * mark

        signed_exposure = (qty * mark) / (equity * leverage) if notional else 0.0
        initial_margin = notional / leverage if notional else 0.0
        margin_base = initial_margin if initial_margin > 0 else float(snapshot.maintenance_margin or 0.0)
        equity_to_margin = equity / max(margin_base, 1e-9) if margin_base > 0 else 1.0
        time_fraction = max(float(position.time_in_position_seconds), 0.0) / self.time_window_seconds

        out = np.asarray(
            [
                np.clip(signed_exposure, -1.0, 1.0),
                float(position.unrealized_pnl) / equity,
                leverage,
                equity_to_margin,
                max(time_fraction, 0.0),
            ],
            dtype=np.float32,
        )
        if out.shape != (5,) or not np.isfinite(out).all():
            raise ValueError("account observation must be a finite vector of shape (5,)")
        return out


class AccountObservationProvider:
    """Canonical raw-account-state -> snapshot -> normalized-observation adapter.

    Deployment code supplies only a callable that returns the provider-neutral raw
    account state. This class owns the conversion to ``AccountSnapshot`` and the
    normalization into the five RL account features, preventing paper/live callers
    from choosing their own adaptation semantics.
    """

    def __init__(
        self,
        snapshot_provider: Callable[..., AccountSnapshot | Mapping[str, Any]],
        *,
        window_bars: int = 60,
        bar_seconds: float = 60.0,
        max_age_ms: int = 5000,
    ) -> None:
        self.snapshot_provider = snapshot_provider
        self.builder = AccountObservationBuilder(window_bars=window_bars, bar_seconds=bar_seconds)
        if int(max_age_ms) <= 0:
            raise ValueError("max_age_ms must be positive")
        self.max_age_ms = int(max_age_ms)

    def snapshot(self, symbol: str, *, now_ms: int | None = None) -> AccountSnapshot:
        raw = self.snapshot_provider(symbol, now_ms=now_ms, max_age_ms=self.max_age_ms)
        return raw if isinstance(raw, AccountSnapshot) else AccountSnapshot.from_mapping(raw)

    def observation(self, symbol: str, *, now_ms: int | None = None) -> np.ndarray:
        return self.builder.build(self.snapshot(symbol, now_ms=now_ms))



def build_account_observation(
    snapshot: AccountSnapshot | Mapping[str, Any], *, window_bars: int = 60, bar_seconds: float = 60.0
) -> np.ndarray:
    """Convenience wrapper for callers that don't need to retain a builder object."""

    return AccountObservationBuilder(window_bars=window_bars, bar_seconds=bar_seconds).build(snapshot)
