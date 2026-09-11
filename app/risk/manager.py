from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import deque, defaultdict
import numpy as np
from typing import Any
from .drift import rolling_sharpe, psi, kl_divergence, per_feature_drift

@dataclass
class RiskConfig:
    daily_loss_limit_fraction: float = 0.02
    max_leverage: float = 3.0
    max_position_fraction: float = 0.25
    max_concurrent_positions: int = 3
    vol_window: int = 60
    vol_z_threshold: float = 3.0
    ws_disconnect_seconds: float = 30.0
    rest_error_threshold: int = 5
    rest_error_window_seconds: float = 60.0
    rolling_sharpe_window: int = 60
    sharpe_floor: float = -1.0
    sharpe_decay_fraction: float = 0.50
    sharpe_decay_consecutive_days: int = 3
    daily_sharpe_window_days: int = 20
    psi_threshold: float = 0.20
    kl_threshold: float = 0.10
    flatten_on_connectivity_failure: bool = False

@dataclass
class RiskDecision:
    allowed: bool
    action: int
    reasons: list[str] = field(default_factory=list)
    flatten: bool = False

class RiskManager:
    """Policy-independent safety layer. Daily Sharpe pauses are evaluated on completed days only."""
    def __init__(self, config: RiskConfig | None = None):
        self.cfg=config or RiskConfig(); self.starting_equity=None; self.day=None; self.day_start_equity=None
        self.high_watermark=None; self.returns=deque(maxlen=max(1000,self.cfg.rolling_sharpe_window*4)); self.live_features=deque(maxlen=5000)
        self.training_features=None; self.training_feature_frame=None; self.baseline_sharpe=None; self.last_sharpe=None; self.last_sharpe_decay=None; self.ws_disconnected_since=None; self.rest_errors=deque(); self.paused=False; self.flags=[]
        self._day_returns=defaultdict(list); self._completed_daily_returns=deque(maxlen=max(365,int(self.cfg.daily_sharpe_window_days)*4))
        self.last_daily_sharpe=None; self.last_daily_decay=None; self.sharpe_floor_streak=0; self.oos_decay_streak=0

    def _finalize_day(self, day):
        values=self._day_returns.pop(day,[])
        if not values: return None
        daily=(float(np.prod(1.0+np.asarray(values,dtype=float))-1.0))
        self._completed_daily_returns.append(daily)
        from .sharpe_decay import annualized_sharpe, sharpe_decay
        if len(self._completed_daily_returns) >= max(2,int(self.cfg.daily_sharpe_window_days)):
            w=list(self._completed_daily_returns)[-int(self.cfg.daily_sharpe_window_days):]
            sh=annualized_sharpe(w,252.0); self.last_daily_sharpe=sh
            floor_breach=bool(np.isfinite(sh) and sh < self.cfg.sharpe_floor)
            self.sharpe_floor_streak=self.sharpe_floor_streak+1 if floor_breach else 0
            if self.baseline_sharpe is not None:
                dec=sharpe_decay(sh,self.baseline_sharpe,self.cfg.sharpe_decay_fraction); self.last_daily_decay=dec.decay_fraction
                self.oos_decay_streak=self.oos_decay_streak+1 if dec.breached else 0
        return daily

    def _reset_day(self,equity,now):
        d=now.date()
        if self.day != d:
            if self.day is not None: self._finalize_day(self.day)
            self.day=d; self.day_start_equity=equity

    def observe(self, *, equity: float|None, return_t: float|None=None, short_vol: float|None=None, rolling_vol_mean: float|None=None, rolling_vol_std: float|None=None, now: datetime|None=None, ws_connected: bool=True, rest_error: bool=False, feature_values=None):
        now=now or datetime.now(timezone.utc)
        if equity is not None:
            equity=float(equity)
            if self.starting_equity is None: self.starting_equity=equity; self.high_watermark=equity
            self._reset_day(equity,now); self.high_watermark=max(self.high_watermark,equity)
        elif self.day != now.date():
            self._reset_day(None,now)
        if return_t is not None:
            rt=float(return_t); self.returns.append(rt); self._day_returns[self.day].append(rt) if self.day is not None else None
        if feature_values is not None: self.live_features.extend(float(x) for x in feature_values if x==x)
        if ws_connected: self.ws_disconnected_since=None
        elif self.ws_disconnected_since is None: self.ws_disconnected_since=now
        cutoff=now.timestamp()-self.cfg.rest_error_window_seconds
        if rest_error: self.rest_errors.append(now.timestamp())
        while self.rest_errors and self.rest_errors[0]<cutoff: self.rest_errors.popleft()
        reasons=[]
        if equity is not None and self.day_start_equity and equity <= self.day_start_equity*(1-self.cfg.daily_loss_limit_fraction): reasons.append("daily_loss_limit")
        if short_vol is not None and rolling_vol_mean is not None and rolling_vol_std is not None and rolling_vol_std>0 and short_vol>rolling_vol_mean+self.cfg.vol_z_threshold*rolling_vol_std: reasons.append("volatility_circuit_breaker")
        if self.ws_disconnected_since and (now-self.ws_disconnected_since).total_seconds()>=self.cfg.ws_disconnect_seconds: reasons.append("websocket_disconnect")
        if len(self.rest_errors)>=self.cfg.rest_error_threshold: reasons.append("rest_error_spike")
        sh=rolling_sharpe(list(self.returns),self.cfg.rolling_sharpe_window) if len(self.returns)>=self.cfg.rolling_sharpe_window else None
        self.last_sharpe=sh
        n_days=max(1,int(self.cfg.sharpe_decay_consecutive_days))
        if self.sharpe_floor_streak>=n_days: reasons.append("rolling_sharpe_decay")
        if self.oos_decay_streak>=n_days: reasons.append("oos_sharpe_decay")
        if self.training_feature_frame is not None and getattr(self,'live_feature_frame',None) is not None and len(self.live_feature_frame)>=100:
            report=self.feature_drift_report()
            psi_hits=[name for name,v in report.items() if v.get('psi',0)>=self.cfg.psi_threshold]
            kl_hits=[name for name,v in report.items() if v.get('kl',0)>=self.cfg.kl_threshold]
            if psi_hits: reasons.append('feature_psi_drift:' + ','.join(psi_hits))
            if kl_hits: reasons.append('feature_kl_drift:' + ','.join(kl_hits))
        elif self.training_features is not None and len(self.live_features)>=100:
            p=psi(self.training_features,list(self.live_features)); k=kl_divergence(self.training_features,list(self.live_features))
            if p>=self.cfg.psi_threshold: reasons.append("feature_psi_drift")
            if k>=self.cfg.kl_threshold: reasons.append("feature_kl_drift")
        if reasons: self.paused=True; self.flags=list(dict.fromkeys(self.flags+reasons))
        return reasons

    def set_baseline_sharpe(self, value):
        if value is not None: self.baseline_sharpe=float(value)
    def set_training_feature_distribution(self, values): self.training_features=[float(x) for x in values if x==x]
    def set_training_feature_frame(self, frame):
        import pandas as pd
        f=pd.DataFrame(frame).copy()
        self.training_feature_frame=f.select_dtypes(include=[np.number])
        self.live_feature_frame=self.training_feature_frame.iloc[0:0].copy()

    def observe_feature_frame(self, frame):
        import pandas as pd
        f=pd.DataFrame(frame).copy().select_dtypes(include=[np.number])
        if not hasattr(self,'live_feature_frame') or self.live_feature_frame is None:
            self.live_feature_frame=f.iloc[0:0].copy()
        self.live_feature_frame=pd.concat([self.live_feature_frame,f],ignore_index=True).tail(5000)

    def feature_drift_report(self):
        if self.training_feature_frame is None or getattr(self,'live_feature_frame',None) is None or len(self.live_feature_frame)<100:
            return {}
        return per_feature_drift(self.training_feature_frame,self.live_feature_frame)
    def volatility_stats(self, short_window: int | None = None):
        w=int(short_window or self.cfg.vol_window)
        if len(self.returns) < max(3, w): return None, None, None
        x=list(self.returns); short=float(np.std(x[-w:], ddof=1)) if len(x[-w:])>1 else 0.0
        history=[float(np.std(x[i-w:i],ddof=1)) for i in range(w,len(x)+1) if len(x[i-w:i])>1]
        if len(history)<2: return short,None,None
        return short,float(np.mean(history)),float(np.std(history,ddof=1))
    def clear_pause(self, *, human_reviewed: bool=False):
        if not human_reviewed: raise PermissionError("risk pause requires human review")
        self.paused=False; self.flags=[]; self.rest_errors.clear(); self.ws_disconnected_since=None; self.sharpe_floor_streak=0; self.oos_decay_streak=0
    def check_action(self, action:int, *, position_qty:float, equity:float, mark_price:float, leverage:float, concurrent_positions:int, requested_qty:float=0.0, capital_ramp=None) -> RiskDecision:
        reasons=list(self.flags); a=int(action)
        hard_flatten={"daily_loss_limit","websocket_disconnect","rest_error_spike","rolling_sharpe_decay","feature_psi_drift","feature_kl_drift"}
        if self.paused and a in (0,1): return RiskDecision(False,3,reasons or ["risk_paused"], self.cfg.flatten_on_connectivity_failure and bool(set(reasons)&hard_flatten))
        if leverage>self.cfg.max_leverage: reasons.append("max_leverage")
        if concurrent_positions>=self.cfg.max_concurrent_positions and a in (0,1) and position_qty==0: reasons.append("max_concurrent_positions")
        if equity>0 and mark_price>0 and abs(position_qty*mark_price)>equity*self.cfg.max_position_fraction and a in (0,1): reasons.append("max_position_size")
        if capital_ramp is not None and a in (0,1) and mark_price>0:
            try: capital_ramp.assert_order_allowed(current_notional=position_qty*mark_price,additional_notional=requested_qty*mark_price,equity=equity)
            except PermissionError: reasons.append("capital_ramp_limit")
        if reasons and a in (0,1): return RiskDecision(False,3,reasons,False)
        return RiskDecision(True,a,reasons,False)
