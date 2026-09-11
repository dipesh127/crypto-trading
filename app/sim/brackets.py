from dataclasses import dataclass
from typing import Iterable
@dataclass(frozen=True)
class Bracket:
    bracket:int; initial_leverage:int; notional_floor:float; notional_cap:float; maint_margin_ratio:float; cum:float=0.0
class BracketTable:
    def __init__(self, rows:Iterable[Bracket]):
        self.rows=sorted(rows,key=lambda x:x.notional_floor)
        if not self.rows: raise ValueError('empty leverage bracket table')
    @classmethod
    def from_binance(cls,data):
        if isinstance(data,dict): data=data.get('brackets',[])
        return cls(Bracket(int(x['bracket']),int(x['initialLeverage']),float(x['notionalFloor']),float(x['notionalCap']),float(x['maintMarginRatio']),float(x.get('cum',0))) for x in data)
    def for_notional(self,n):
        n=abs(float(n))
        for b in self.rows:
            if n <= b.notional_cap: return b
        return self.rows[-1]
    def maintenance_margin(self,notional):
        b=self.for_notional(notional)
        return abs(float(notional))*b.maint_margin_ratio-b.cum
