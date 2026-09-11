import asyncio
from app.monitoring import metrics_payload, observe_request
from app.alerts import AlertDispatcher
from app.sim.execution import AlmgrenChrissExecution
from app.rl.ensemble import EnsemblePolicy, EnsembleMember

class D:
    def __init__(self,v): self.v=v
    def predict(self,obs,deterministic=True): return self.v,None

def test_prometheus_metrics_payload_and_alert_disabled():
    observe_request('GET','/test',200,0.001)
    assert isinstance(metrics_payload(),(bytes,bytearray))
    assert not AlertDispatcher().enabled

def test_ensemble_tie_is_deterministic():
    p=EnsemblePolicy([EnsembleMember(D(1)),EnsembleMember(D(0))]); a,info=p.predict({}); assert a in (0,1) and len(info['votes'])==2

def test_ac_has_monotonic_schedule():
    t,q=AlmgrenChrissExecution(10,steps=5).schedule(); assert all(x>0 for x in q); assert q.sum()>0
