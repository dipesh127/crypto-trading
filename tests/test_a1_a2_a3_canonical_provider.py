import numpy as np
import pytest

from app.rl.account_state import AccountObservationProvider, AccountSnapshot


def test_provider_owns_mapping_to_snapshot_and_normalization():
    calls = []
    def raw(symbol, **kwargs):
        calls.append((symbol, kwargs))
        return {
            'positionAmt': '0.01', 'markPrice': '100000', 'unRealizedProfit': '100',
            'leverage': '5', 'totalMarginBalance': '10000', 'time_in_position_seconds': '180',
        }
    provider = AccountObservationProvider(raw, window_bars=60, bar_seconds=60, max_age_ms=5000)
    got = provider.observation('BTCUSDT')
    expected = np.array([0.02, 0.01, 5.0, 50.0, 0.05], dtype=np.float32)
    np.testing.assert_allclose(got, expected)
    assert calls and calls[0][0] == 'BTCUSDT'
    assert calls[0][1]['max_age_ms'] == 5000


def test_provider_accepts_canonical_snapshot_without_readaptation():
    snap = AccountSnapshot(position_qty=1, mark_price=100, leverage=2, equity=1000, unrealized_pnl=10)
    provider = AccountObservationProvider(lambda symbol, **kwargs: snap, window_bars=10, bar_seconds=60)
    np.testing.assert_allclose(provider.observation('ETHUSDT')[:3], [0.05, 0.01, 2.0])


def test_provider_propagates_provider_errors():
    provider = AccountObservationProvider(lambda symbol, **kwargs: (_ for _ in ()).throw(RuntimeError('stale')))
    with pytest.raises(RuntimeError, match='stale'):
        provider.observation('BTCUSDT')
