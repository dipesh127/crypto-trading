from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd

try:
    import gymnasium as gym
    from gymnasium import spaces
except ImportError:
    class _GymEnv:
        def reset(self, *, seed=None, options=None): return None
    class _Gym: Env = _GymEnv
    gym = _Gym()
    class _Box:
        def __init__(self, low, high, shape, dtype=np.float32): self.low,self.high,self.shape,self.dtype=low,high,shape,dtype
    class _Discrete:
        def __init__(self,n): self.n=n
    class _Dict(dict):
        def __init__(self, d): super().__init__(d)
    class spaces: Box=_Box; Discrete=_Discrete; Dict=_Dict

from .rewards import DifferentialSharpe, shaped_reward
from .account_state import AccountObservationBuilder, AccountSnapshot, PositionSnapshot
ACTIONS = {0:"LONG",1:"SHORT",2:"FLAT",3:"CLOSE"}

def account_observation(position_amt: float, mark_price: float, unrealized_pnl: float, leverage: float,
                        equity: float, maintenance_margin: float = 0.0, time_in_position_seconds: float = 0.0,
                        *, window_bars: int = 60, bar_seconds: float = 60.0) -> np.ndarray:
    """Legacy/testing-only account observation helper.

    Deployment code MUST use ``adapter.account_observation(symbol)`` so raw exchange
    state adaptation and normalization remain under the canonical provider contract.
    This wrapper is retained solely for historical tests/backward compatibility.
    """
    snapshot = AccountSnapshot(
        position_qty=position_amt,
        mark_price=mark_price,
        unrealized_pnl=unrealized_pnl,
        leverage=leverage,
        equity=equity,
        maintenance_margin=maintenance_margin,
        time_in_position_seconds=time_in_position_seconds,
    )
    return AccountObservationBuilder(window_bars=window_bars, bar_seconds=bar_seconds).build(snapshot)


@dataclass
class AccountState:
    position: float = 0.0
    entry_price: float = 0.0
    balance: float = 10_000.0
    peak_equity: float = 10_000.0
    time_in_position: int = 0
    leverage: float = 1.0

class CryptoFuturesEnv(gym.Env):
    """Causal futures RL environment using signed *exposure fraction* as position.

    The market observation is a rolling feature window. Account state is kept separate
    so a shared temporal encoder can process market data before concatenating account state.
    Execution uses the same spread/fee conventions as Phase 3; the environment is intentionally
    one-symbol, one-way, and mark-to-market for fast PPO rollouts.
    """
    metadata={"render_modes":[]}
    def __init__(self,data:pd.DataFrame,feature_cols=None,window=60,initial_cash=10_000.0,
                 fee_rate=0.0005,spread_bps=1.0,slippage_bps=0.5,leverage=1.0,
                 reward_mode="shaped",lambda_cost=1.0,lambda_dd=1.0,differential_eta=0.01,
                 randomize_costs=False,seed=None,funding_col="funding_rate", decision_interval_seconds: float | None = None):
        super().__init__(); self.data=data.copy(); self.data.index=pd.to_datetime(self.data.index,utc=True)
        if len(self.data)<=window+1: raise ValueError("data must contain more than window+1 rows")
        self.feature_cols=list(feature_cols or [c for c in data.columns if pd.api.types.is_numeric_dtype(data[c]) and c not in {"open","high","low","close"}])
        if not self.feature_cols: raise ValueError("feature_cols cannot be empty")
        missing=set(self.feature_cols)-set(self.data.columns)
        if missing: raise ValueError(f"missing feature columns: {sorted(missing)}")
        if "close" not in self.data: raise ValueError("data requires close")
        self.window=int(window); self.initial_cash=float(initial_cash); self.base_fee=float(fee_rate)
        self.base_spread_bps=float(spread_bps); self.base_slippage_bps=float(slippage_bps); self.base_leverage=float(leverage)
        self.reward_mode=reward_mode; self.lambda_cost=float(lambda_cost); self.lambda_dd=float(lambda_dd); self.randomize_costs=bool(randomize_costs)
        self.funding_col=funding_col; self.rng=np.random.default_rng(seed); self.diff_sharpe=DifferentialSharpe(differential_eta)
        inferred_seconds = float(decision_interval_seconds) if decision_interval_seconds is not None else self._infer_decision_interval_seconds()
        self.account_observation_builder=AccountObservationBuilder(window_bars=self.window, bar_seconds=inferred_seconds)
        self.observation_space=spaces.Dict({"market":spaces.Box(-np.inf,np.inf,(self.window,len(self.feature_cols)),dtype=np.float32),"account":spaces.Box(-np.inf,np.inf,(5,),dtype=np.float32)})
        self.action_space=spaces.Discrete(4); self._continuous_action_space=spaces.Box(-1.0,1.0,(1,),dtype=np.float32); self._reset_costs()
    def _infer_decision_interval_seconds(self) -> float:
        """Infer the primary decision timeframe from chronological UTC index spacing."""
        if len(self.data.index) < 2:
            raise ValueError("at least two timestamps are required to infer decision interval")
        deltas = pd.Series(self.data.index).diff().dropna().dt.total_seconds()
        positive = deltas[deltas > 0]
        if positive.empty:
            raise ValueError("could not infer a positive decision interval from data timestamps")
        return float(positive.median())

    def _reset_costs(self):
        self.fee_rate=self.base_fee*self.rng.uniform(.8,1.2) if self.randomize_costs else self.base_fee
        self.spread_bps=self.base_spread_bps; self.slippage_bps=self.base_slippage_bps*(self.rng.uniform(.75,1.5) if self.randomize_costs else 1.0)
    def _price(self,i):
        return float(self.data.iloc[i].get("mark_price",self.data.iloc[i]["close"]))
    def _equity(self,i=None):
        i=self.i if i is None else i; px=self._price(i); unreal=self.position*self._entry_notional*(px/self.entry_price-1.0) if self.position and self.entry_price else 0.0
        return self.balance+unreal
    def _obs(self):
        x=self.data.iloc[self.i-self.window+1:self.i+1][self.feature_cols].to_numpy(dtype=np.float32); x=np.nan_to_num(x,nan=0.0,posinf=0.0,neginf=0.0)
        px=self._price(self.i); unreal=self.position*self._entry_notional*(px/self.entry_price-1.0) if self.position and self.entry_price else 0.0
        equity=self.balance+unreal
        # The environment stores an RL exposure target; the shared contract takes
        # the exchange's base-asset quantity used by paper/live execution.
        qty = self.position * equity * self.leverage / px if px and equity > 0 else 0.0
        account=self.account_observation_builder.build(AccountSnapshot(
            equity=equity,
            maintenance_margin=0.0,
            position=PositionSnapshot(
                position_qty=qty,
                mark_price=px,
                unrealized_pnl=unreal,
                leverage=self.leverage,
                time_in_position_seconds=self.time_in_position * self.account_observation_builder.bar_seconds,
            ),
        ))
        return {"market":x,"account":account}
    def _target(self,action):
        if isinstance(action,np.ndarray): return float(np.clip(action.reshape(-1)[0],-1,1))
        return {0:1.0,1:-1.0,2:0.0,3:0.0}[int(action)]
    def reset(self,*,seed=None,options=None):
        super().reset(seed=seed)
        if seed is not None: self.rng=np.random.default_rng(seed)
        o=options or {}; self.start=max(self.window,int(o.get("start",self.window))); self.end=min(len(self.data)-1,int(o.get("end",len(self.data)-1)))
        if self.end<=self.start: raise ValueError("end must be greater than start")
        self.i=self.start; self.position=0.0; self.entry_price=0.0; self._entry_notional=0.0; self.balance=self.initial_cash; self.peak_equity=self.initial_cash; self.time_in_position=0; self.leverage=self.base_leverage; self.prev_drawdown=0.0; self.diff_sharpe.reset(); self._reset_costs(); self.trade_count=0; self.turnover=0.0
        return self._obs(),{"equity":self.initial_cash,"timestamp":self.data.index[self.i]}
    def step(self,action):
        price=self._price(self.i); equity_before=self._equity(); target=self._target(action); delta=target-self.position
        # Position is signed fraction of equity. Exposure notional is locked at entry and updated on changes.
        new_notional=max(equity_before,0.0)*self.leverage*abs(target)
        trade_notional=abs(delta)*max(equity_before,0.0)*self.leverage
        exec_rate=self.fee_rate+self.spread_bps/10000/2+self.slippage_bps/10000
        cost=trade_notional*exec_rate; self.balance-=cost
        if delta:
            if self.position and np.sign(self.position)!=np.sign(target):
                self.balance+=self.position*self._entry_notional*(price/self.entry_price-1.0)
            if target:
                self.entry_price=price; self._entry_notional=new_notional
            else:
                self.entry_price=0.0; self._entry_notional=0.0
            self.position=target; self.trade_count+=1; self.turnover+=trade_notional
        next_i=self.i+1; next_price=self._price(next_i)
        if self.position and self.entry_price:
            pnl=self.position*self._entry_notional*(next_price/self.entry_price-1.0)
        else: pnl=0.0
        # Realize bar-to-bar PnL so equity remains stable and rewards are additive.
        self.balance+=pnl
        self.entry_price=next_price if self.position else 0.0
        if self.position: self._entry_notional=max(self.balance,0.0)*self.leverage*abs(self.position)
        else: self._entry_notional=0.0
        if self.position and self.funding_col in self.data.columns:
            fr=self.data.iloc[next_i].get(self.funding_col); ts=self.data.index[next_i]
            if pd.notna(fr) and ts.hour in (0,8,16) and ts.minute==0:
                self.balance-=self.position*self._entry_notional*float(fr)
        equity=self.balance; self.peak_equity=max(self.peak_equity,equity); dd=max(0.0,1-equity/max(self.peak_equity,1e-9))
        if self.position: self.time_in_position+=1
        else: self.time_in_position=0
        if self.reward_mode=="differential_sharpe": reward=self.diff_sharpe.update((equity-equity_before)/max(abs(equity_before),1e-9))
        else: reward=shaped_reward(pnl,float(delta),self.fee_rate,self.spread_bps/10000/2+self.slippage_bps/10000,dd,self.prev_drawdown,self.lambda_cost,self.lambda_dd)
        self.prev_drawdown=dd; self.i=next_i; terminated=self.i>=self.end; truncated=False
        info={"equity":equity,"pnl":pnl,"drawdown":dd,"position":self.position,"turnover":self.turnover,"trade_count":self.trade_count,"timestamp":self.data.index[self.i],"fee_rate":self.fee_rate,"slippage_bps":self.slippage_bps}
        return self._obs(),float(reward),terminated,truncated,info

class ContinuousCryptoFuturesEnv(CryptoFuturesEnv):
    def __init__(self,*args,**kwargs): super().__init__(*args,**kwargs); self.action_space=self._continuous_action_space
