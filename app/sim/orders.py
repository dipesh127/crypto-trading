from dataclasses import dataclass,field
from enum import Enum
class OrderType(str,Enum):
    MARKET='MARKET'; LIMIT='LIMIT'; STOP_MARKET='STOP_MARKET'; STOP_LIMIT='STOP_LIMIT'; TAKE_PROFIT_MARKET='TAKE_PROFIT_MARKET'; TRAILING_STOP_MARKET='TRAILING_STOP_MARKET'
@dataclass
class Order:
    id:int; side:int; qty:float; type:OrderType; price:float|None=None; stop_price:float|None=None; callback_rate:float|None=None; activation_price:float|None=None; reduce_only:bool=False; maker:bool=False; active:bool=True; triggered:bool=False; trail_extreme:float|None=None; leverage:int=1
@dataclass
class Fill:
    timestamp:object; order_id:int; side:int; qty:float; price:float; fee:float; reason:str='signal'
