from __future__ import annotations
import numpy as np, pandas as pd

class TrainOnlyScaler:
    def __init__(self, method='zscore'):
        if method not in {'zscore','minmax'}: raise ValueError(method)
        self.method=method; self.columns=None; self.params={}; self.fitted=False
    def fit(self, frame):
        df=pd.DataFrame(frame).copy(); self.columns=list(df.columns); self.params={}
        for c in self.columns:
            x=pd.to_numeric(df[c],errors='coerce')
            if self.method=='zscore': self.params[c]=(float(x.mean()),float(x.std(ddof=1)))
            else: self.params[c]=(float(x.min()),float(x.max()))
        self.fitted=True; return self
    def transform(self, frame):
        if not self.fitted: raise RuntimeError('scaler must be fit on training data first')
        df=pd.DataFrame(frame).copy()
        for c in self.columns:
            x=pd.to_numeric(df[c],errors='coerce'); a,b=self.params[c]
            df[c]=(x-a)/(b if self.method=='zscore' else b-a) if self.method=='zscore' else (x-a)/(b-a)
            if self.method=='zscore' and b==0: df[c]=0.0
            if self.method=='minmax' and b==a: df[c]=0.0
        return df
    def fit_transform(self, frame): return self.fit(frame).transform(frame)
    def state_dict(self): return {'method':self.method,'columns':self.columns,'params':self.params}
    @classmethod
    def from_state_dict(cls,state):
        s=cls(state['method']); s.columns=state['columns']; s.params={k:tuple(v) for k,v in state['params'].items()}; s.fitted=True; return s
