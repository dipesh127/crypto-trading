import argparse, json
from app.risk import RiskConfig, PromotionChecklist
p=argparse.ArgumentParser(); p.add_argument('--weeks',type=int,required=True); p.add_argument('--trades',type=int,required=True); p.add_argument('--max-drawdown',type=float,required=True); p.add_argument('--human-signoff',action='store_true'); a=p.parse_args()
ok,checks=PromotionChecklist().evaluate(profitable_weeks=a.weeks,trade_count=a.trades,max_drawdown=a.max_drawdown,human_signoff=a.human_signoff)
print(json.dumps({'eligible':ok,'checks':checks,'auto_promotion':False},indent=2))
if not ok: raise SystemExit(2)
