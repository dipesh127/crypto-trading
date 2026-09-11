from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import json

@dataclass
class RampState:
    stage: int = 0
    target_fraction: float = 0.10
    approved_capital: float = 0.0
    activated_at: str = ""
    reviewer: str = ""
    human_approved: bool = False
    pnl_positive: bool = False
    max_drawdown: float = 0.0

class CapitalRampController:
    """Runtime-enforced capital allocation. Never allows an order above the active stage."""
    DEFAULT_LEVELS=(0.10,0.25,0.50,0.75,1.0)
    def __init__(self, path="artifacts/go_live/capital_ramp.json", levels=DEFAULT_LEVELS):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True); self.levels=tuple(levels)
        self.state=self._load()
    def _load(self):
        if self.path.exists(): return RampState(**json.loads(self.path.read_text()))
        s=RampState(target_fraction=self.levels[0]); self._save(s); return s
    def _save(self,s=None):
        s=s or self.state; self.path.write_text(json.dumps(asdict(s),indent=2,sort_keys=True))
    def authorize(self, *, approved_capital: float, reviewer: str, human_approved: bool, stage: int=0):
        if approved_capital<=0: raise ValueError("approved capital must be positive")
        if not reviewer.strip() or not human_approved: raise PermissionError("capital ramp requires named human approval")
        if stage<0 or stage>=len(self.levels): raise ValueError("invalid ramp stage")
        self.state=RampState(stage=stage,target_fraction=self.levels[stage],approved_capital=float(approved_capital),activated_at=datetime.now(timezone.utc).isoformat(),reviewer=reviewer.strip(),human_approved=True)
        self._save(); return self.state
    def activate_initial(self, *, approved_capital: float, reviewer: str, human_approved: bool):
        if self.state.approved_capital>0 and self.state.human_approved:
            raise PermissionError("initial capital already activated; use advance_ramp for later stages")
        return self.authorize(approved_capital=approved_capital, reviewer=reviewer, human_approved=human_approved, stage=0)
    def validate_runtime_stage(self, requested_stage:int):
        if not self.state.human_approved or self.state.approved_capital<=0:
            raise PermissionError("no approved live capital ramp exists")
        if int(requested_stage)!=self.state.stage:
            raise PermissionError(f"requested ramp stage {requested_stage} is not the approved runtime stage {self.state.stage}; use the human-approved ramp advancement workflow")
        return self.state
    @property
    def max_capital(self): return self.state.approved_capital*self.state.target_fraction
    def max_notional(self, equity: float|None=None):
        if not self.state.human_approved or self.state.approved_capital<=0: return 0.0
        base=min(self.state.approved_capital,float(equity)) if equity is not None and equity>0 else self.state.approved_capital
        return base*self.state.target_fraction
    def assert_order_allowed(self, *, current_notional: float, additional_notional: float, equity: float):
        limit=self.max_notional(equity)
        if limit<=0: raise PermissionError("capital ramp is not authorized")
        if abs(current_notional)+max(0.0,additional_notional)>limit+1e-12:
            raise PermissionError(f"capital ramp exceeded: requested={abs(current_notional)+max(0.0,additional_notional):.8f}, limit={limit:.8f}")
    def can_advance(self, *, days_at_stage:int,pnl_positive:bool,max_drawdown:float,max_allowed_drawdown:float)->bool:
        return self.state.stage<len(self.levels)-1 and days_at_stage>=7 and pnl_positive and max_drawdown<=max_allowed_drawdown
    def approve_advance(self, *, reviewer:str,human_approved:bool,pnl_positive:bool,max_drawdown:float):
        if not human_approved or not reviewer.strip(): raise PermissionError("ramp advancement requires human approval")
        if self.state.stage>=len(self.levels)-1: return self.state
        self.state.stage+=1; self.state.target_fraction=self.levels[self.state.stage]; self.state.reviewer=reviewer.strip(); self.state.human_approved=True; self.state.pnl_positive=pnl_positive; self.state.max_drawdown=max_drawdown; self.state.activated_at=datetime.now(timezone.utc).isoformat(); self._save(); return self.state
