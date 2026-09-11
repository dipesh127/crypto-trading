from dataclasses import dataclass
import pandas as pd
@dataclass(frozen=True)
class Split:
    train:pd.DataFrame; validation:pd.DataFrame; test:pd.DataFrame

def walk_forward(df,train=0.6,validation=0.2,test=0.2):
    if abs(train+validation+test-1)>1e-9: raise ValueError('fractions must sum to 1')
    n=len(df); a=int(n*train); b=a+int(n*validation); return Split(df.iloc[:a].copy(),df.iloc[a:b].copy(),df.iloc[b:].copy())

def purged_embargo_splits(df,n_splits=5,purge=0,embargo=0):
    n=len(df); folds=[]
    for i in range(n_splits):
        lo=i*n//n_splits; hi=(i+1)*n//n_splits
        test=range(lo,hi); train_idx=list(range(0,max(0,lo-purge)))+list(range(min(n,hi+embargo),n))
        folds.append((train_idx,list(test)))
    return folds
