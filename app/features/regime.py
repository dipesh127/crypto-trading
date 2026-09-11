from __future__ import annotations
import numpy as np, pandas as pd
from sklearn.cluster import KMeans
from sklearn.mixture import GaussianMixture

def regime_inputs(close, high, low, volume, window=20):
    c=pd.Series(close,dtype='float64'); h=pd.Series(high,dtype='float64'); l=pd.Series(low,dtype='float64'); v=pd.Series(volume,dtype='float64')
    ret=np.log(c/c.shift(1)); vol=ret.rolling(window).std(); trend=(c-c.shift(window))/c.shift(window); tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1); trend_strength=tr.rolling(window).mean()/c.abs().replace(0,np.nan); vstd=v.rolling(window).std(ddof=1); vol_z=(v-v.rolling(window).mean())/vstd.replace(0,np.nan); vol_z=vol_z.fillna(0.0)
    return pd.DataFrame({'volatility':vol,'trend_strength':trend_strength,'volume_z':vol_z,'trend_return':trend})

class MarketRegimeClassifier:
    def __init__(self,n_regimes=4,method='kmeans',random_state=42):
        if method not in {'kmeans','gmm'}: raise ValueError(method)
        self.n_regimes=n_regimes; self.method=method; self.random_state=random_state; self.model=None; self.columns=None; self.label_map={}
    def fit(self, X):
        df=pd.DataFrame(X); self.columns=list(df.columns); valid=df.dropna();
        self.model=KMeans(n_clusters=self.n_regimes,n_init=20,random_state=self.random_state) if self.method=='kmeans' else GaussianMixture(n_components=self.n_regimes,random_state=self.random_state,n_init=5)
        self.model.fit(valid[self.columns]); self._build_semantic_map(valid); return self
    def _build_semantic_map(self, df):
        labels=self.model.predict(df[self.columns]); tmp=df.copy(); tmp['_label']=labels; stats=tmp.groupby('_label').mean(numeric_only=True); self.label_map={int(k):int(rank) for rank,k in enumerate(stats['trend_return'].sort_values().index)}
    def predict(self,X):
        if self.model is None: raise RuntimeError('classifier not fitted')
        df=pd.DataFrame(X); out=pd.Series(pd.NA,index=df.index,dtype='Int64'); valid=df[self.columns].notna().all(axis=1); raw=self.model.predict(df.loc[valid,self.columns]); out.loc[valid]=[self.label_map.get(int(x),int(x)) for x in raw]; return out
    def fit_predict(self,X): self.fit(X); return self.predict(X)
    def state_dict(self): return {'n_regimes':self.n_regimes,'method':self.method,'random_state':self.random_state,'columns':self.columns,'label_map':self.label_map,'model':self.model}
