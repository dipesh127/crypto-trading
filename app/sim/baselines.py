import numpy as np, pandas as pd
def sma_crossover(df,fast=20,slow=50):
    s=df['close'].rolling(fast).mean()>df['close'].rolling(slow).mean(); return s.astype(int).shift(1).fillna(0)
def rsi_mean_reversion(df,period=14,low=30,high=70):
    d=df['close'].diff(); up=d.clip(lower=0).ewm(alpha=1/period,adjust=False).mean(); dn=(-d.clip(upper=0)).ewm(alpha=1/period,adjust=False).mean(); r=100-100/(1+up/dn.replace(0,np.nan)); return pd.Series(np.where(r<low,1,np.where(r>high,-1,0)),index=df.index).shift(1).fillna(0)
def buy_hold(df): return pd.Series(1,index=df.index).shift(1).fillna(0)
