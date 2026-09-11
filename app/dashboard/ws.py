from __future__ import annotations
import asyncio
import json
from dataclasses import dataclass, field
from app.monitoring import WS_CLIENTS

@dataclass
class Subscription:
    modes: set[str] = field(default_factory=lambda: {"PAPER_TESTNET"})
    symbols: set[str] = field(default_factory=set)

class DashboardHub:
    def __init__(self):
        self.clients: dict[object,Subscription] = {}
        self._sequence: dict[tuple[str,str,str],int] = {}
    async def connect(self,ws):
        await ws.accept(); self.clients[ws]=Subscription()
        if WS_CLIENTS: WS_CLIENTS.set(len(self.clients))
    def disconnect(self,ws):
        self.clients.pop(ws,None)
        if WS_CLIENTS: WS_CLIENTS.set(len(self.clients))
    def subscribe(self,ws,modes=None,symbols=None):
        sub=self.clients.get(ws)
        if sub is None: return
        if modes is not None: sub.modes={str(x).upper() for x in modes}
        if symbols is not None: sub.symbols={str(x).upper() for x in symbols}
    def sequence_key(self, channel, mode='', symbol=''):
        return (str(channel), str(mode or '').upper(), str(symbol or '').upper())

    def current_sequence(self, channel, mode='', symbol=''):
        return self._sequence.get(self.sequence_key(channel,mode,symbol),0)

    def _next_sequence(self,channel,mode='',symbol=''):
        key=self.sequence_key(channel,mode,symbol); self._sequence[key]=self._sequence.get(key,0)+1; return self._sequence[key]
    def _interested(self,sub,event):
        mode=str(event.get('mode','')).upper(); symbol=str(event.get('symbol','')).upper()
        if mode not in {'*','MARKET'} and mode not in sub.modes: return False
        if sub.symbols and symbol and symbol not in sub.symbols: return False
        return True
    async def publish(self,event):
        event=dict(event); channel=str(event.get('channel') or event.get('type') or 'event'); event['channel']=channel; mode=str(event.get('mode','')).upper(); symbol=str(event.get('symbol','')).upper(); event['seq']=self._next_sequence(channel,mode,symbol); event['scope']={'mode':mode,'symbol':symbol}
        message=json.dumps(event,default=str); dead=[]
        for ws,sub in tuple(self.clients.items()):
            if not self._interested(sub,event): continue
            try: await ws.send_text(message)
            except Exception: dead.append(ws)
        for ws in dead: self.disconnect(ws)

async def heartbeat(hub,service,mode="PAPER_TESTNET",interval=1.0):
    previous=None
    while True:
        try:
            current=await service.overview(mode)
            delta=current if previous is None else {k:v for k,v in current.items() if previous.get(k)!=v}
            if delta:
                await hub.publish({'type':'execution_state_delta','channel':'execution_state','mode':mode,'symbol':'','data':delta})
            previous=current
        except asyncio.CancelledError: raise
        except Exception: pass
        await asyncio.sleep(interval)

async def heartbeat_all(hub,service,modes=("PAPER_TESTNET","LIVE"),interval=1.0):
    tasks=[asyncio.create_task(heartbeat(hub,service,mode,interval),name=f"dashboard-heartbeat-{mode.lower()}") for mode in modes]
    try: await asyncio.gather(*tasks)
    finally:
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)

async def redis_market_bridge(hub,redis_url):
    """Forward market stream events with an explicit MARKET channel and symbol filter semantics."""
    try:
        import redis.asyncio as redis
        client=redis.from_url(redis_url,decode_responses=True)
        last_ids={k:'$' for k in ('kline','trade','bookTicker','mark','liquidation','ticker')}
        try:
            while True:
                result=await client.xread({f'market:{k}':last_ids[k] for k in last_ids},block=1000,count=100)
                for stream,entries in result:
                    kind=stream.split(':',1)[1]
                    for entry_id,fields in entries:
                        last_ids[kind]=entry_id; raw=fields.get('data','{}')
                        try: data=json.loads(raw)
                        except Exception: data={'raw':raw}
                        symbol=str(data.get('s') or data.get('symbol') or '').upper()
                        await hub.publish({'type':'market_tick','channel':'market_tick','mode':'MARKET','symbol':symbol,'kind':kind,'data':data,'ts':entry_id})
        finally: await client.close()
    except asyncio.CancelledError: raise
    except Exception: return
