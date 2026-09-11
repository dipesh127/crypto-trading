from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from .risk.promotion import PromotionChecklist


@dataclass(frozen=True)
class GoLiveEvidence:
    profitable_weeks: int
    trade_count: int
    max_drawdown: float
    market_regimes: tuple[str, ...]
    risk_controls_tested: bool
    human_signoff: bool
    signoff_name: str
    signoff_at: str
    model_checkpoint: str
    feature_set_version: str
    paper_start: str
    paper_end: str
    notes: str = ""

    @classmethod
    def load(cls, path: str | Path) -> "GoLiveEvidence":
        data = json.loads(Path(path).read_text())
        data["market_regimes"] = tuple(data.get("market_regimes", ()))
        return cls(**data)

    def validate(self, checklist: PromotionChecklist | None = None) -> tuple[bool, dict[str, Any]]:
        c = checklist or PromotionChecklist()
        ok, checks = c.evaluate(
            profitable_weeks=self.profitable_weeks,
            trade_count=self.trade_count,
            max_drawdown=self.max_drawdown,
            human_signoff=self.human_signoff,
        )
        checks["distinct_market_regimes"] = {"value": list(self.market_regimes), "ok": len(set(self.market_regimes)) >= 3}
        checks["risk_controls_tested"] = self.risk_controls_tested
        checks["signoff_identity"] = bool(self.signoff_name.strip())
        checks["signoff_timestamp"] = _fresh_signoff(self.signoff_at)
        checks["paper_duration"] = {"value": [self.paper_start, self.paper_end], "ok": _paper_duration_ok(self.paper_start, self.paper_end, self.profitable_weeks)}
        return ok and all(v if isinstance(v, bool) else v.get("ok", False) for v in checks.values()), checks

    def digest(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), default=list).encode()
        return hashlib.sha256(raw).hexdigest()


def _paper_duration_ok(start: str, end: str, profitable_weeks: int) -> bool:
    try:
        a = datetime.fromisoformat(start.replace("Z", "+00:00"))
        b = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return b >= a and (b - a).total_seconds() >= max(1, profitable_weeks) * 7 * 86400
    except Exception:
        return False


def _fresh_signoff(value: str, max_age_hours: int = 72) -> bool:
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - ts <= timedelta(hours=max_age_hours)
    except Exception:
        return False


@dataclass(frozen=True)
class LiveSecurityAttestation:
    live_trading_enabled: bool
    api_key_present: bool
    api_secret_present: bool
    ip_whitelisted: bool
    withdrawals_disabled: bool
    production_endpoint: bool
    human_signoff: bool

    @classmethod
    def from_environment(cls) -> "LiveSecurityAttestation":
        from .config import get_settings
        s = get_settings()
        base = s.binance_rest_base_url.lower()
        return cls(
            live_trading_enabled=bool(s.live_trading_enabled),
            api_key_present=bool(s.binance_api_key),
            api_secret_present=bool(s.binance_api_secret),
            ip_whitelisted=bool(s.binance_ip_whitelisted),
            withdrawals_disabled=bool(s.binance_withdrawals_disabled),
            production_endpoint="fapi.binance.com" in base and "testnet" not in base,
            human_signoff=bool(s.live_human_signoff),
        )

    def validate(self) -> tuple[bool, list[str]]:
        checks = asdict(self)
        failed = [k for k, v in checks.items() if not v]
        return not failed, failed


def authorize_live(evidence_path: str | Path, *, checklist: PromotionChecklist | None = None) -> dict[str, Any]:
    evidence = GoLiveEvidence.load(evidence_path)
    evidence_ok, checks = evidence.validate(checklist)
    security = LiveSecurityAttestation.from_environment()
    security_ok, security_failed = security.validate()
    result = {
        "authorized": evidence_ok and security_ok,
        "evidence_digest": evidence.digest(),
        "evidence_checks": checks,
        "security_checks": asdict(security),
        "security_failed": security_failed,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if not result["authorized"]:
        raise PermissionError(json.dumps(result, indent=2, default=str))
    return result
