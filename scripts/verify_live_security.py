#!/usr/bin/env python3
"""Fail-closed production security attestation.

Binance does not expose API-key permission/IP settings through the trading API; these
items must be manually verified in the Binance API-management console and explicitly
attested via environment flags before live authorization.
"""
import json
from app.golive import LiveSecurityAttestation
s=LiveSecurityAttestation.from_environment(); ok,failed=s.validate()
print(json.dumps({'ready':ok,'checks':s.__dict__,'manual_verification_required':['IP whitelist','withdrawals disabled'] if not failed else failed},indent=2))
raise SystemExit(0 if ok else 2)
