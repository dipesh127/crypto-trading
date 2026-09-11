from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd

@dataclass(frozen=True)
class RegimeWindow:
    name:str; start:pd.Timestamp; end:pd.Timestamp

def chronological_regime_windows(df, n=3):
    d=df.sort_index(); chunks=[x for x in np.array_split(d,n) if len(x)]
    names=['bull','bear','range']
    return [RegimeWindow(names[i] if i<len(names) else f'regime_{i}',x.index[0],x.index[-1]) for i,x in enumerate(chunks)]

def walkforward_windows(df, train_bars, validation_bars, test_bars, step=None):
    d=df.sort_index(); step=step or test_bars; out=[]; i=0
    while i+train_bars+validation_bars+test_bars<=len(d):
        a=i; b=a+train_bars; c=b+validation_bars; e=c+test_bars
        out.append((d.iloc[a:b],d.iloc[b:c],d.iloc[c:e])); i+=step
    return out

def purged_embargo_splits(df, n_splits=3, purge_bars=1, embargo_bars=1, min_train_bars=100, min_validation_bars=50):
    """Chronological expanding-window CV with a purge gap before validation and an embargo after it.

    No row in validation can be used to train a fold. ``purge_bars`` removes observations immediately
    before validation from the training set; ``embargo_bars`` reserves observations immediately after
    validation so adjacent folds cannot leak labels/features across the boundary.
    """
    d=df.sort_index()
    n=len(d)
    if n_splits < 1: raise ValueError('n_splits must be >= 1')
    usable=n-min_train_bars-embargo_bars
    if usable < min_validation_bars: return []
    val_size=max(min_validation_bars, usable//n_splits)
    splits=[]
    for k in range(n_splits):
        val_start=min_train_bars+k*val_size
        val_end=min(n-embargo_bars, val_start+val_size)
        train_end=val_start-purge_bars
        if train_end < min_train_bars or val_end-val_start < min_validation_bars: continue
        train=d.iloc[:train_end].copy(); val=d.iloc[val_start:val_end].copy()
        if len(train) and len(val): splits.append((train,val))
    return splits
