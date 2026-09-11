import asyncio
import numpy as np
import pandas as pd
from decimal import Decimal

from app.live import BinanceLiveExecutionAdapter
from app.paper import BinancePaperExecutionAdapter, ExecutionState, InternalPosition
from app.rl.account_state import AccountObservationBuilder, AccountSnapshot, PositionSnapshot
from app.rl.env import CryptoFuturesEnv
from app.rl.live_policy import LiveFeatureObservationBuilder


def test_canonical_account_builder_matches_legacy_contract():
    b = AccountObservationBuilder(window_bars=60, bar_seconds=60)
    snap = AccountSnapshot(
        position_qty=0.01,
        mark_price=100_000,
        unrealized_pnl=100,
        leverage=5,
        equity=10_000,
        maintenance_margin=0,
        time_in_position_seconds=180,
    )
    got = b.build(snap)
    expected = np.array([0.02, 0.01, 5.0, 50.0, 0.05], dtype=np.float32)
    np.testing.assert_allclose(got, expected)


def test_mapping_aliases_build_identical_observation():
    b = AccountObservationBuilder(window_bars=60, bar_seconds=60)
    mapped = b.build({
        "positionAmt": "0.01", "markPrice": "100000", "unRealizedProfit": "100",
        "leverage": "5", "totalMarginBalance": "10000", "totalMaintMargin": "0",
        "time_in_position_seconds": 180,
    })
    direct = b.build(AccountSnapshot(0.01, 100000, 100, 5, 10000, 0, 180))
    np.testing.assert_array_equal(mapped, direct)


def test_training_environment_uses_canonical_builder():
    idx = pd.date_range("2026-01-01", periods=8, freq="min", tz="UTC")
    df = pd.DataFrame({"close": np.linspace(100, 101, 8), "feature": np.arange(8, dtype=float)}, index=idx)
    env = CryptoFuturesEnv(df, feature_cols=["feature"], window=2, initial_cash=1000.0)
    env.reset()
    expected = env.account_observation_builder.build(AccountSnapshot(equity=1000.0))
    np.testing.assert_array_equal(env._obs()["account"], expected)


def test_builder_rejects_invalid_window():
    try:
        AccountObservationBuilder(window_bars=0)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid window must fail")


def test_env_paper_and_live_have_exact_account_observation_parity():
    """One synthetic exchange snapshot must produce one exact RL vector everywhere."""
    now_ms = 2_000_000
    snapshot = AccountSnapshot(
        equity=10_000.0,
        maintenance_margin=0.0,
        position=PositionSnapshot(
            position_qty=0.01, mark_price=100_000.0, unrealized_pnl=0.0,
            leverage=5.0, time_in_position_seconds=900.0,
        ),
    )
    expected = AccountObservationBuilder(window_bars=60, bar_seconds=300).build(snapshot)

    idx = pd.date_range("2026-01-01", periods=70, freq="5min", tz="UTC")
    env = CryptoFuturesEnv(
        pd.DataFrame({"close": 100_000.0, "feature": np.arange(70, dtype=float)}, index=idx),
        feature_cols=["feature"], window=60, initial_cash=10_000.0, leverage=5.0,
    )
    env.reset()
    env.position = 0.02  # 0.01 BTC * $100k / ($10k * 5)
    env.entry_price = env._price(env.i)
    env._entry_notional = 1_000.0
    env.time_in_position = 3  # three five-minute bars
    np.testing.assert_array_equal(env._obs()["account"], expected)

    class Rest:
        base_url = "https://testnet.binancefuture.com"
        session = object()

    for adapter_type in (BinancePaperExecutionAdapter, BinanceLiveExecutionAdapter):
        adapter = adapter_type(
            Rest(), account_window_bars=60, account_decision_interval_seconds=300.0,
            account_max_age_ms=30_000,
        )
        adapter.ws_connected = True
        adapter.state = ExecutionState()
        adapter.state.user_stream_connected = True
        adapter.state.user_stream_authenticated = True
        adapter.state.last_user_stream_message_time_ms = now_ms
        adapter.state.last_user_stream_transport_activity_time_ms = now_ms
        adapter.state.account_snapshot = {
            "_equity": 10_000.0, "totalMaintMargin": 0.0,
            "_source": "authenticated_user_stream", "_authoritative": True,
        }
        adapter.state.positions["BTCUSDT"] = InternalPosition(
            "BTCUSDT", position_amt=Decimal("0.01"), mark_price=Decimal("100000"),
            leverage=Decimal("5"), opened_at_ms=now_ms - 900_000,
            open_time_known=True,
        )
        np.testing.assert_array_equal(adapter.account_observation("BTCUSDT", now_ms=now_ms), expected)


def test_live_feature_builder_uses_canonical_account_observation_builder():
    frame = pd.DataFrame({"feature": [1.0, 2.0, 3.0]})
    snapshot = AccountSnapshot(
        equity=10_000.0,
        position=PositionSnapshot(
            position_qty=0.01, mark_price=100_000.0, unrealized_pnl=100.0,
            leverage=5.0, time_in_position_seconds=180.0,
        ),
    )
    live = LiveFeatureObservationBuilder(
        lambda: frame, ["feature"], window=3,
        account_snapshot_provider=lambda: snapshot,
        account_decision_interval_seconds=60.0,
    )
    observation = asyncio.run(live.get_observation())
    expected = AccountObservationBuilder(window_bars=3, bar_seconds=60.0).build(snapshot)
    np.testing.assert_array_equal(observation["account"], expected)
