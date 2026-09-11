from __future__ import annotations
import math
import numpy as np

def rolling_sharpe(returns, window: int = 60, annualization: float = 1.0) -> float:
    x=np.asarray(returns,dtype=float); x=x[np.isfinite(x)]
    if x.size < max(2, window): return float("nan")
    z=x[-window:]; s=z.std(ddof=1)
    return float(z.mean()/s*math.sqrt(annualization)) if s > 0 else 0.0

def _bins(x, edges): return np.histogram(np.asarray(x,dtype=float), bins=edges)[0].astype(float)

def psi(training, live, bins: int = 10, eps: float = 1e-6) -> float:
    a=np.asarray(training,dtype=float); b=np.asarray(live,dtype=float); a=a[np.isfinite(a)]; b=b[np.isfinite(b)]
    if a.size < 2 or b.size < 2: raise ValueError("need training and live samples")
    edges=np.unique(np.quantile(a,np.linspace(0,1,bins+1)))
    if edges.size < 2: return 0.0
    pa=_bins(a,edges); pb=_bins(b,edges)
    pa=pa/pa.sum(); pb=pb/pb.sum(); pa=np.clip(pa,eps,None); pb=np.clip(pb,eps,None)
    return float(np.sum((pb-pa)*np.log(pb/pa)))

def kl_divergence(training, live, bins: int = 20, eps: float = 1e-6) -> float:
    a=np.asarray(training,dtype=float); b=np.asarray(live,dtype=float); a=a[np.isfinite(a)]; b=b[np.isfinite(b)]
    if a.size < 2 or b.size < 2: raise ValueError("need training and live samples")
    lo=min(a.min(),b.min()); hi=max(a.max(),b.max())
    if lo==hi: return 0.0
    edges=np.linspace(lo,hi,bins+1); pa=_bins(a,edges); pb=_bins(b,edges)
    pa=(pa+eps)/(pa.sum()+eps*len(pa)); pb=(pb+eps)/(pb.sum()+eps*len(pb))
    return float(np.sum(pb*np.log(pb/pa)))


def per_feature_drift(training, live, bins: int = 10, eps: float = 1e-6):
    """Compute PSI/KL independently for each numeric feature column."""
    import pandas as pd
    ta=pd.DataFrame(training)
    la=pd.DataFrame(live)
    common=[c for c in ta.columns if c in la.columns]
    result={}
    for c in common:
        a=pd.to_numeric(ta[c],errors='coerce').to_numpy(float); b=pd.to_numeric(la[c],errors='coerce').to_numpy(float)
        a=a[np.isfinite(a)]; b=b[np.isfinite(b)]
        if len(a)<2 or len(b)<2: continue
        result[str(c)]={'psi':psi(a,b,bins=bins,eps=eps),'kl':kl_divergence(a,b,bins=max(20,bins),eps=eps)}
    return result
