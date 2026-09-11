import asyncio
from app.binance import BinanceREST

class Resp:
    status=500
    headers={}
    async def text(self): return 'boom'
    async def json(self): return {}
    async def __aenter__(self): return self
    async def __aexit__(self,*a): pass

class Session:
    def request(self,*a,**kw): return Resp()


def test_rest_failure_callback_runs_on_each_retry():
    async def run():
        rest=BinanceREST('http://example.invalid')
        rest.session=Session()
        seen=[]
        async def cb(exc, **ctx): seen.append((ctx['method'],ctx['path']))
        rest.set_error_callback(cb)
        try: await rest.request('GET','/x')
        except RuntimeError: pass
        assert len(seen)==4
    asyncio.run(run())
