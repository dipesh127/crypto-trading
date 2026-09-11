#!/usr/bin/env python3
import argparse, json
from app.golive import GoLiveEvidence, LiveSecurityAttestation
from app.risk.promotion import PromotionChecklist

p=argparse.ArgumentParser(description="Fail-closed Phase 8 go-live preflight; never places orders")
p.add_argument("--evidence", required=True)
p.add_argument("--min-profitable-weeks", type=int, default=8)
p.add_argument("--min-trades", type=int, default=200)
p.add_argument("--max-drawdown", type=float, default=0.15)
a=p.parse_args()

e=GoLiveEvidence.load(a.evidence)
ok, checks=e.validate(PromotionChecklist(a.min_profitable_weeks,a.min_trades,a.max_drawdown,True))
s=LiveSecurityAttestation.from_environment(); sok, failed=s.validate()
result={"ready":ok and sok,"evidence_checks":checks,"security":s.__dict__,"security_failed":failed,"evidence_digest":e.digest()}
print(json.dumps(result,indent=2,default=str))
raise SystemExit(0 if result["ready"] else 2)
