import numpy as np
import pandas as pd

from app.rl.env import CryptoFuturesEnv
from app.paper import BinancePaperExecutionAdapter


class DummyREST:
    base_url = 'https://testnet.binancefuture.com'
    session = object()


def test_adapter_owns_account_observation_contract_and_timeframe():
    adapter = BinancePaperExecutionAdapter(
        DummyREST(),
        execution_mode='PAPER_TESTNET',
        account_window_bars=20,
        account_decision_interval_seconds=300.0,
        account_max_age_ms=10000,
    )
    adapter.state.account_snapshot = {
        '_equity': 10000.0,
        '_source': 'authenticated_user_stream',
        '_authoritative': True,
        '_last_event_time_ms': 1_000_000,
        '_last_user_stream_message_time_ms': 1_000_000,
    }
    adapter.ws_connected = True
    adapter.state.last_user_stream_message_time_ms = 1_000_000
    adapter.state.positions['BTCUSDT'] = type('P', (), {
        'symbol': 'BTCUSDT', 'position_amt': 0.01, 'mark_price': 100000.0,
        'unrealized_pnl': 100.0, 'leverage': 5.0,
        'entry_price': 99000.0, 'liquidation_price': 0.0,
        'isolated_wallet': 0.0, 'margin_type': 'ISOLATED', 'opened_at_ms': 999000,
    })()
    obs = adapter.account_observation('BTCUSDT', now_ms=1_001_000)
    assert len(obs) == 5
    assert np.isfinite(obs).all()
    # 1000ms / (20 * 300s) = 1/6000.
    assert np.isclose(obs[4], 2.0 / (20 * 300.0))
    assert adapter._account_observation_provider.builder.bar_seconds == 300.0


def test_env_infers_decision_interval_from_data_index():
    idx = pd.date_range('2026-01-01', periods=70, freq='5min', tz='UTC')
    df = pd.DataFrame({'close': np.linspace(100, 110, len(idx)), 'feat': np.arange(len(idx), dtype=float)}, index=idx)
    env = CryptoFuturesEnv(df, feature_cols=['feat'], window=10)
    assert np.isclose(env.account_observation_builder.bar_seconds, 300.0)


def test_deployment_scripts_do_not_construct_account_builder():
    from pathlib import Path
    for name in ('scripts/paper_trade.py', 'scripts/live_trade.py'):
        text = Path(name).read_text()
        assert 'AccountObservationBuilder' not in text
        assert 'AccountSnapshot' not in text
        assert 'account_observation_provider = AccountObservationProvider' not in text
        assert 'adapter.account_observation_async(a.symbol)' in text
