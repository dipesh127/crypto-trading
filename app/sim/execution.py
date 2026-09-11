import math
import numpy as np
from .orders import Order,OrderType,Fill

class ExecutionModel:
    def __init__(self,fee_schedule,impact=False,impact_coeff=1.0,execution_model="spread_sqrt",ac_config=None,spread_bps=1.0):
        self.fees=fee_schedule; self.impact=impact; self.impact_coeff=impact_coeff; self.execution_model=execution_model; self.spread_bps=float(spread_bps)
        self.ac_config=dict(ac_config or {})
        self.ac=None if execution_model!="almgren_chriss" else AlmgrenChrissExecution(**({"total_qty":1.0,**self.ac_config}))
        self._ac_state={}

    def market_price(self,mid,spread,side,sigma=0,qty=0,adv=0):
        px=mid + (spread/2 if side>0 else -spread/2)
        if self.execution_model=="almgren_chriss" and adv and qty:
            cfg=self.ac or AlmgrenChrissExecution(total_qty=max(abs(float(qty)),1e-12),**self.ac_config)
            px=cfg.impact_price(mid,side,qty,adv)
        elif self.impact and adv and sigma:
            px += side*mid*sigma*self.impact_coeff*math.sqrt(abs(qty)/max(adv,1e-12))
        return px

    def _ac_slice(self,order):
        state=self._ac_state.get(order.id)
        if state is None:
            cfg_kwargs={k:v for k,v in self.ac_config.items() if k!='total_qty'}
            cfg=AlmgrenChrissExecution(total_qty=max(abs(float(order.qty)),1e-12),**cfg_kwargs)
            _, slices=cfg.schedule(); state={"cfg":cfg,"slices":np.asarray(slices,dtype=float),"idx":0}; self._ac_state[order.id]=state
        if state["idx"]>=len(state["slices"]): return min(float(order.qty),0.0)
        qty=min(float(order.qty),float(state["slices"][state["idx"]])); state["idx"]+=1
        return max(qty,0.0)

    def try_fill(self,order,bar,mid,spread=0,sigma=0,adv=0):
        side=order.side; lo,hi=float(bar['low']),float(bar['high']); o=float(bar['open']); px=None; fill_qty=float(order.qty)
        if order.type==OrderType.MARKET:
            if self.execution_model=="almgren_chriss":
                fill_qty=self._ac_slice(order)
                if fill_qty<=0: return None
                cfg=self._ac_state[order.id]["cfg"]
                px=mid + (spread/2 if side>0 else -spread/2)
                px=cfg.impact_price(px,side,fill_qty,adv)
            else: px=self.market_price(mid,spread,side,sigma,order.qty,adv)
        elif order.type==OrderType.LIMIT:
            if side>0 and lo<=order.price: px=min(order.price,o)
            elif side<0 and hi>=order.price: px=max(order.price,o)
        elif order.type in (OrderType.STOP_MARKET,OrderType.TAKE_PROFIT_MARKET):
            trig=(side>0 and hi>=order.stop_price) or (side<0 and lo<=order.stop_price)
            if trig:
                px=self.market_price(mid,spread,side,sigma,order.qty,adv)
        elif order.type==OrderType.STOP_LIMIT:
            trig=(side>0 and hi>=order.stop_price) or (side<0 and lo<=order.stop_price)
            if trig:
                order.triggered=True
                if side>0 and lo<=order.price: px=order.price
                elif side<0 and hi>=order.price: px=order.price
        elif order.type==OrderType.TRAILING_STOP_MARKET:
            if order.activation_price is not None: activated=(side>0 and hi>=order.activation_price) or (side<0 and lo<=order.activation_price)
            else: activated=True
            if activated:
                if order.trail_extreme is None: order.trail_extreme=hi if side<0 else lo
                order.trail_extreme=max(order.trail_extreme,hi) if side<0 else min(order.trail_extreme,lo)
                extreme=order.trail_extreme; trigger=extreme*(1+side*order.callback_rate/100)
                if (side<0 and lo<=trigger) or (side>0 and hi>=trigger): px=self.market_price(mid,spread,side,sigma,order.qty,adv)
        if px is None: return None
        fee=self.fees.commission(px*fill_qty,'maker' if order.maker else 'taker')
        if self.execution_model=="almgren_chriss" and order.qty-fill_qty<=1e-12: self._ac_state.pop(order.id,None)
        return Fill(bar.name,order.id,side,fill_qty,px,fee,reason='almgren_chriss_slice' if self.execution_model=='almgren_chriss' else 'signal')


class AlmgrenChrissExecution:
    """Deterministic Almgren-Chriss optimal liquidation schedule and impact execution."""
    def __init__(self,total_qty,risk_aversion=1e-6,volatility=0.02,temporary_impact=0.01,permanent_impact=0.0,horizon=1.0,steps=10):
        if total_qty<=0 or horizon<=0 or steps<1: raise ValueError('invalid Almgren-Chriss parameters')
        self.total_qty=float(total_qty); self.risk_aversion=float(risk_aversion); self.volatility=float(volatility)
        self.temporary_impact=float(temporary_impact); self.permanent_impact=float(permanent_impact); self.horizon=float(horizon); self.steps=int(steps)
    def schedule(self):
        sigma=max(self.volatility,1e-12); eta=max(self.temporary_impact,1e-12); gamma=max(self.risk_aversion,0.0)
        kappa=math.sqrt(gamma*sigma*sigma/eta) if gamma>0 else 0.0
        times=np.linspace(0,self.horizon,self.steps+1)
        if kappa==0: remaining=self.total_qty*(1-times/self.horizon)
        else: remaining=self.total_qty*np.sinh(kappa*(self.horizon-times))/np.sinh(kappa*self.horizon)
        return times[1:],-np.diff(remaining)
    def impact_components(self,mid_price, side, slice_qty, adv):
        # AC-style trade-rate v = Q / horizon_step. Scale v by ADV so eta/gamma remain stable across symbols.
        v=abs(float(slice_qty))/max(float(adv),1e-12)
        temp=float(self.temporary_impact)*v
        perm=float(self.permanent_impact)*v
        return temp,perm

    def impact_price(self,mid_price,side,slice_qty,adv):
        temp,perm=self.impact_components(mid_price,side,slice_qty,adv)
        return float(mid_price*(1+float(side)*(temp+perm)))

    def temporary_impact_price(self,mid_price,slice_qty,adv):
        side=1 if float(slice_qty)>=0 else -1
        temp,_=self.impact_components(mid_price,side,abs(float(slice_qty)),adv)
        return float(mid_price*(1+side*temp))


def almgren_chriss_schedule(total_qty, **kwargs):
    return AlmgrenChrissExecution(total_qty,**kwargs).schedule()
