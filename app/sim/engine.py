from dataclasses import dataclass
import pandas as pd, numpy as np
from .orders import Order,OrderType
from .execution import ExecutionModel
from .liquidation import liquidation_trigger
from .metrics import performance,significance,monte_carlo_trade_ci
from .baselines import sma_crossover,rsi_mean_reversion,buy_hold

@dataclass
class Position:
    qty:float=0; entry_price:float=0; margin:float=0; realized:float=0; opened_at:object=None

class Simulator:
    def __init__(self,fee_schedule,brackets_by_symbol,initial_cash=10000,spread_bps=1,impact=False,execution_model="spread_sqrt",ac_config=None,latency_ms=100):
        self.fees=fee_schedule; self.brackets=brackets_by_symbol; self.initial_cash=initial_cash; self.spread_bps=float(spread_bps); self.latency_ms=float(max(0,latency_ms)); self.execution=ExecutionModel(fee_schedule,impact,spread_bps=spread_bps,execution_model=execution_model,ac_config=ac_config)

    def _run_core(self,bars,orders=None,signals=None,symbol=None,mark_col='mark_price',funding_col='funding_rate'):
        bars=bars.copy(); bars.index=pd.to_datetime(bars.index,utc=True); orders=list(orders or []); signals=signals
        cash=float(self.initial_cash); pos=Position(); fills=[]; trade_pnl=[]; equity=[]; exposure=[]; holding_hours=[]; turnover=0; next_id=1; prev_ts=None
        for ts,row in bars.iterrows():
            if signals is not None:
                sig=float(signals.loc[ts]) if ts in signals.index else 0
                if sig and np.sign(sig)!=np.sign(pos.qty):
                    if pos.qty:
                        o=Order(next_id,-1 if pos.qty>0 else 1,abs(pos.qty),OrderType.MARKET,reduce_only=True); o.eligible_ts=ts+pd.to_timedelta(self.latency_ms,unit="ms"); orders.append(o); next_id+=1
                    o=Order(next_id,1 if sig>0 else -1,abs(sig),OrderType.MARKET); o.eligible_ts=ts+pd.to_timedelta(self.latency_ms,unit="ms"); orders.append(o); next_id+=1
            if pos.qty and funding_col in row and pd.notna(row[funding_col]) and prev_ts is not None and ts != prev_ts:
                if getattr(ts,'hour',None) in (0,8,16) and getattr(ts,'minute',None)==0:
                    cash -= pos.qty*float(row.get(mark_col,row['close']))*float(row[funding_col])
            mid=float(row.get(mark_col,row['close'])); spread=mid*self.spread_bps/10000.0
            sigma=float(row.get('volatility',0) or 0); adv=float(row.get('volume',0) or 0)
            for o in list(orders):
                if getattr(o,"eligible_ts",ts) > ts: continue
                f=self.execution.try_fill(o,row,mid,spread,sigma,adv)
                if not f: continue
                old=pos.qty; delta=f.side*f.qty; new=old+delta
                fee=f.fee; cash-=fee; turnover+=abs(f.qty*f.price); fills.append(f); o.qty=max(0.0,float(o.qty)-float(f.qty));
                if o.qty<=1e-12: orders.remove(o)
                if old == 0:
                    pos=Position(qty=new,entry_price=f.price,margin=abs(new*f.price)/max(int(getattr(o,'leverage',1)),1),opened_at=ts)
                elif np.sign(old)==np.sign(new):
                    if abs(new) < abs(old):
                        closed=abs(old)-abs(new); pnl=closed*(f.price-pos.entry_price)*np.sign(old); cash+=pnl; trade_pnl.append(pnl-fee)
                        if abs(new)>0: pos.qty=new
                        else: pos=Position();
                        if pos.qty==0 and pos.opened_at is not None: holding_hours.append((ts-pos.opened_at).total_seconds()/3600)
                    else:
                        pos.entry_price=(abs(old)*pos.entry_price+abs(delta)*f.price)/(abs(old)+abs(delta)); pos.qty=new
                else:
                    closed=abs(old); pnl=closed*(f.price-pos.entry_price)*np.sign(old); cash+=pnl; trade_pnl.append(pnl-fee)
                    if pos.opened_at is not None: holding_hours.append((ts-pos.opened_at).total_seconds()/3600)
                    residual=new
                    if residual:
                        pos=Position(qty=residual,entry_price=f.price,margin=abs(residual*f.price)/max(int(getattr(o,'leverage',1)),1),opened_at=ts)
                    else: pos=Position()
            mark=mid; unreal=pos.qty*(mark-pos.entry_price) if pos.qty else 0; eq=cash+unreal; equity.append(eq); exposure.append(bool(pos.qty))
            if pos.qty and symbol in self.brackets:
                hit,lp=liquidation_trigger(mark,pos.entry_price,pos.qty,pos.margin,self.brackets[symbol],np.sign(pos.qty))
                if hit:
                    pnl=pos.qty*(mark-pos.entry_price); cash+=pnl; trade_pnl.append(pnl); 
                    if pos.opened_at is not None: holding_hours.append((ts-pos.opened_at).total_seconds()/3600)
                    pos=Position(); equity[-1]=cash
            prev_ts=ts
        # If a position remains open, report its observed holding duration without pretending it was closed.
        if pos.qty and pos.opened_at is not None and len(bars): holding_hours.append((bars.index[-1]-pos.opened_at).total_seconds()/3600)
        eq_series=pd.Series(equity,index=bars.index,name='equity')
        metrics=performance(eq_series,trade_pnl)
        metrics.update(turnover=turnover,trade_count=len(fills),exposure_time=float(np.mean(exposure)) if exposure else 0,
                       average_holding_period_hours=float(np.mean(holding_hours)) if holding_hours else 0.0,
                       average_holding_period_minutes=float(np.mean(holding_hours)*60) if holding_hours else 0.0)
        metrics['monte_carlo']=monte_carlo_trade_ci(trade_pnl,initial_cash=self.initial_cash,timestamps=[f.timestamp for f in fills]) if trade_pnl else None
        metrics['significance']=significance(eq_series.pct_change().dropna())
        return {'equity':eq_series,'fills':fills,'trade_pnl':trade_pnl,'metrics':metrics,'holding_periods_hours':holding_hours}

    def run(self,bars,orders=None,signals=None,symbol=None,mark_col='mark_price',funding_col='funding_rate',auto_baselines=True):
        result=self._run_core(bars,orders,signals,symbol,mark_col,funding_col)
        if auto_baselines:
            baseline_signals={'sma_crossover':sma_crossover(bars),'rsi_mean_reversion':rsi_mean_reversion(bars),'buy_hold':buy_hold(bars)}
            comparisons={}
            for name,sig in baseline_signals.items():
                br=self._run_core(bars,signals=sig,symbol=symbol,mark_col=mark_col,funding_col=funding_col)
                comparisons[name]=br['metrics']
            # Buy-and-hold benchmark is also reported directly from price for an unambiguous passive reference.
            close=pd.Series(bars['close'],index=bars.index).astype(float)
            benchmark_equity=self.initial_cash*(close/close.iloc[0])
            comparisons['buy_and_hold_benchmark']=performance(benchmark_equity)
            result['benchmarks']=comparisons
            result['benchmark_equity']=benchmark_equity
            strat_ret=result['equity'].pct_change().dropna().to_numpy()
            bench_ret=benchmark_equity.pct_change().dropna().to_numpy()
            n=min(len(strat_ret),len(bench_ret)); result['metrics']['significance']=significance(strat_ret[-n:],bench_ret[-n:]) if n else result['metrics']['significance']
            result['metrics']['benchmark_total_return']=float(benchmark_equity.iloc[-1]/benchmark_equity.iloc[0]-1)
        return result
