from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json
import numpy as np

@dataclass
class EnsembleMember:
    model: object
    weight: float = 1.0
    name: str = "model"

class EnsemblePolicy:
    """Inference-time ensemble for discrete or continuous SB3 policies.

    Discrete policies vote on Long/Short/Flat/Close actions. Continuous policies are
    averaged by weight and clipped to [-1, 1]. No member is allowed to place orders directly.
    """
    def __init__(self,members,mode='weighted_vote'):
        if not members: raise ValueError('ensemble requires at least one member')
        self.members=[m if isinstance(m,EnsembleMember) else EnsembleMember(m) for m in members]
        self.mode=mode
        total=sum(max(0.0,m.weight) for m in self.members)
        if total<=0: raise ValueError('ensemble weights must contain a positive value')
        self._weights=np.asarray([max(0.0,m.weight)/total for m in self.members])
    def predict(self,observation,deterministic=True):
        actions=[]
        for m in self.members:
            a,_=m.model.predict(observation,deterministic=deterministic); actions.append(a)
        arr=np.asarray(actions)
        if np.issubdtype(arr.dtype,np.integer) or all(np.asarray(a).size==1 and float(np.asarray(a).reshape(-1)[0]).is_integer() for a in actions):
            vals=np.asarray([int(np.asarray(a).reshape(-1)[0]) for a in actions])
            scores={}
            for i,v in enumerate(vals): scores[v]=scores.get(v,0.0)+float(self._weights[i])
            best=max(scores,key=lambda k:(scores[k],-k))
            return int(best), {'votes':vals.tolist(),'weights':self._weights.tolist(),'scores':scores}
        values=np.asarray([float(np.asarray(a).reshape(-1)[0]) for a in actions])
        return float(np.clip(np.sum(values*self._weights),-1,1)), {'actions':values.tolist(),'weights':self._weights.tolist()}

    @classmethod
    def load(cls,paths,weights=None,algorithm='ppo'):
        from stable_baselines3 import PPO,SAC
        alg=(PPO if algorithm.lower()=='ppo' else SAC)
        if weights is None: weights=[1.0]*len(paths)
        return cls([EnsembleMember(alg.load(str(p)),float(w),Path(p).stem) for p,w in zip(paths,weights)])

    def manifest(self):
        return {'mode':self.mode,'members':[{'name':m.name,'weight':float(w)} for m,w in zip(self.members,self._weights)]}

    def save_manifest(self,path):
        p=Path(path); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(self.manifest(),indent=2)); return p
