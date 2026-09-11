from __future__ import annotations
import json, shutil
from pathlib import Path

class ChampionRegistry:
    def __init__(self, root='artifacts/models'):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True); self.registry=self.root/'registry.json'
        if not self.registry.exists(): self._save({"champion":None,"challenger":None,"history":[]})
    def _load(self): return json.loads(self.registry.read_text())
    def _save(self,x): self.registry.write_text(json.dumps(x,indent=2,sort_keys=True))
    def register_challenger(self,model_path,metadata_path):
        d=self._load(); d['challenger']={'model':str(model_path),'metadata':str(metadata_path),'status':'shadow'}; self._save(d); return d['challenger']
    def promote(self):
        d=self._load(); ch=d.get('challenger')
        if not ch: raise ValueError('no challenger registered')
        old=d.get('champion');
        if old: d['history'].append(old)
        ch['status']='champion'; d['champion']=ch; d['challenger']=None; self._save(d); return ch
    def rollback(self):
        d=self._load();
        if not d['history']: raise ValueError('no previous champion available')
        current=d.get('champion'); previous=d['history'].pop();
        if current: current['status']='rolled_back'; d['history'].append(current)
        previous['status']='champion'; d['champion']=previous; self._save(d); return previous
    def promote_human(self, *, reviewer:str):
        if not reviewer.strip(): raise PermissionError("reviewer required")
        d=self._load(); ch=d.get('challenger')
        if not ch or ch.get('status')!='shadow': raise ValueError('challenger must be in shadow state')
        d.setdefault('approval_audit',[]).append({'action':'PROMOTE','reviewer':reviewer.strip(),'at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),'model':ch.get('model')})
        return self.promote()
    def rollback_human(self, *, reviewer:str):
        if not reviewer.strip(): raise PermissionError("reviewer required")
        d=self._load(); d.setdefault('approval_audit',[]).append({'action':'ROLLBACK','reviewer':reviewer.strip(),'at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()}); self._save(d); return self.rollback()
    def status(self): return self._load()
