#!/usr/bin/env python3
import argparse
from app.governance.capital import CapitalRampController
p=argparse.ArgumentParser(description='Human-approved capital ramp advancement')
p.add_argument('--days',type=int,required=True); p.add_argument('--pnl-positive',action='store_true'); p.add_argument('--max-drawdown',type=float,required=True); p.add_argument('--max-allowed-drawdown',type=float,default=.15); p.add_argument('--reviewer',required=True); p.add_argument('--human-signoff',action='store_true'); p.add_argument('--path',default='artifacts/go_live/capital_ramp.json')
a=p.parse_args(); r=CapitalRampController(a.path)
if not r.can_advance(days_at_stage=a.days,pnl_positive=a.pnl_positive,max_drawdown=a.max_drawdown,max_allowed_drawdown=a.max_allowed_drawdown): raise SystemExit('Ramp advancement criteria not met')
if not a.human_signoff: raise SystemExit('Ramp advancement requires --human-signoff')
print(r.approve_advance(reviewer=a.reviewer,human_approved=True,pnl_positive=a.pnl_positive,max_drawdown=a.max_drawdown))
