import argparse, json
import numpy as np
from app.risk import parametric_var, expected_shortfall, rolling_sharpe
p=argparse.ArgumentParser(); p.add_argument('--returns',required=True,help='comma-separated decimal returns'); p.add_argument('--alpha',type=float,default=.99); p.add_argument('--window',type=int,default=60); a=p.parse_args()
r=np.array([float(x) for x in a.returns.split(',')],dtype=float)
print(json.dumps({'alpha':a.alpha,'parametric_var':parametric_var(r,a.alpha),'expected_shortfall':expected_shortfall(r,a.alpha),'rolling_sharpe':rolling_sharpe(r,a.window)},indent=2))
