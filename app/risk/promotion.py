from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone

@dataclass(frozen=True)
class PromotionChecklist:
    min_profitable_weeks: int = 8
    min_trades: int = 200
    max_drawdown: float = 0.15
    required_human_signoff: bool = True
    def evaluate(self, *, profitable_weeks: int, trade_count: int, max_drawdown: float, human_signoff: bool) -> tuple[bool,dict]:
        checks={"profitable_weeks":profitable_weeks>=self.min_profitable_weeks,"trade_count":trade_count>=self.min_trades,"max_drawdown":max_drawdown<=self.max_drawdown,"human_signoff":(human_signoff if self.required_human_signoff else True)}
        return all(checks.values()),checks

@dataclass(frozen=True)
class CapitalRamp:
    levels: tuple[float,...]=(0.10,0.25,0.50,0.75,1.0)
    min_days_per_level: int=7
    def target_fraction(self, level:int)->float:
        if level<0 or level>=len(self.levels): raise ValueError("invalid ramp level")
        return self.levels[level]
    def next_level_allowed(self, level:int, days_at_level:int, *, pnl_positive:bool, max_drawdown:float, max_allowed_drawdown:float)->bool:
        return level < len(self.levels)-1 and days_at_level>=self.min_days_per_level and pnl_positive and max_drawdown<=max_allowed_drawdown
