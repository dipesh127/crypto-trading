import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from app.golive import GoLiveEvidence, LiveSecurityAttestation
from app.config import get_settings


def evidence(**overrides):
    data = {
        "profitable_weeks": 8,
        "trade_count": 250,
        "max_drawdown": 0.10,
        "market_regimes": ["bull", "bear", "range"],
        "risk_controls_tested": True,
        "human_signoff": True,
        "signoff_name": "Reviewer",
        "signoff_at": datetime.now(timezone.utc).isoformat(),
        "model_checkpoint": "champion.zip",
        "feature_set_version": "phase2-v1",
        "paper_start": "2026-01-01T00:00:00Z",
        "paper_end": "2026-03-01T00:00:00Z",
    }
    data.update(overrides)
    return GoLiveEvidence(**data)


def test_golive_requires_three_regimes_and_risk_controls():
    ok, checks = evidence().validate()
    assert ok
    assert checks["distinct_market_regimes"]["ok"]

    ok, _ = evidence(market_regimes=("bull", "bear")).validate()
    assert not ok

    ok, _ = evidence(risk_controls_tested=False).validate()
    assert not ok


def test_stale_signoff_fails():
    old = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
    ok, _ = evidence(signoff_at=old).validate()
    assert not ok


def test_security_attestation_fails_closed(monkeypatch):
    for key in [
        "LIVE_TRADING_ENABLED", "BINANCE_IP_WHITELISTED", "BINANCE_WITHDRAWALS_DISABLED",
        "LIVE_HUMAN_SIGNOFF"
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BINANCE_API_KEY", "x")
    monkeypatch.setenv("BINANCE_API_SECRET", "y")
    monkeypatch.setenv("BINANCE_REST_BASE_URL", "https://fapi.binance.com")
    get_settings.cache_clear()
    a = LiveSecurityAttestation.from_environment()
    get_settings.cache_clear()
    ok, failed = a.validate()
    assert not ok
    assert "live_trading_enabled" in failed
    assert "ip_whitelisted" in failed


def test_digest_is_stable():
    e = evidence()
    assert e.digest() == e.digest()
    assert len(e.digest()) == 64
