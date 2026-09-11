from dataclasses import dataclass

# Binance USDⓈ-M Futures standard USDT maker/taker schedule observed 2026-09-08.
# See Binance fee page; keep configurable because VIP status can change.
FEES = {
    0:(0.00020,0.00050),1:(0.00018,0.00050),2:(0.00016,0.00040),
    3:(0.00012,0.00032),4:(0.00010,0.00030),5:(0.00008,0.00027),
    6:(0.00006,0.00025),7:(0.00004,0.00022),8:(0.00002,0.00020),9:(0.0,0.00017)
}
@dataclass(frozen=True)
class FeeSchedule:
    vip:int=0
    maker:float|None=None
    taker:float|None=None
    def __post_init__(self):
        if self.vip not in FEES: raise ValueError('VIP must be 0..9')
        if self.maker is None: object.__setattr__(self,'maker',FEES[self.vip][0])
        if self.taker is None: object.__setattr__(self,'taker',FEES[self.vip][1])
    def commission(self,notional,liquidity='taker'): return abs(notional)*(self.maker if liquidity=='maker' else self.taker)
