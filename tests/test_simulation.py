import pandas as pd
from app.sim.fees import FeeSchedule
from app.sim.brackets import Bracket,BracketTable
from app.sim.liquidation import isolated_liquidation_price
from app.sim.metrics import newey_west_ttest,monte_carlo_trade_ci

def test_fee(): assert FeeSchedule(0).commission(10000,'taker')==5

def test_bracket_maintenance():
 b=BracketTable([Bracket(1,20,0,50000,.004,0),Bracket(2,10,50000,100000,.005,50)])
 assert b.maintenance_margin(25000)==100
 assert b.maintenance_margin(75000)==325

def test_liquidation_piecewise():
 b=BracketTable([Bracket(1,20,0,50000,.004,0)])
 p=isolated_liquidation_price(100,1,10,b,1)
 assert round(p,6)==90.361446

def test_nw_and_mc():
 x=[.01,-.005,.004,.002,-.003]*10
 assert newey_west_ttest(x)['pvalue']>=0
 ci=monte_carlo_trade_ci(x,100,1); assert len(ci['return_ci'])==3
