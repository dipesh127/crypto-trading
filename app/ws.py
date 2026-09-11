import asyncio,json,logging,websockets
log=logging.getLogger(__name__)

class CombinedStreams:
    def __init__(self,base_url,streams,handler):
        self.url=base_url.rstrip("/")+"/stream?streams="+"/".join(s.lower() for s in streams)
        self.handler=handler; self.stop=False
    async def run(self):
        delay=1
        while not self.stop:
            try:
                async with websockets.connect(self.url,ping_interval=20,ping_timeout=20,max_size=8*1024*1024,max_queue=10000) as ws:
                    delay=1
                    async for raw in ws: await self.handler(json.loads(raw).get("data",{}))
            except asyncio.CancelledError: raise
            except Exception:
                try:
                    from .monitoring import observe_ws_reconnect
                    observe_ws_reconnect("combined_market")
                except Exception: pass
                log.exception("market websocket disconnected")
                await asyncio.sleep(delay); delay=min(delay*2,30)
