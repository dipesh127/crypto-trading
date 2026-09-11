import asyncio
from datetime import datetime, timezone
from app.dashboard.service import DashboardService

def test_drawdown_is_negative_underwater_series():
    class Cache:
        async def get(self,k): return None
        async def set(self,k,v): pass
    class Conn:
        async def fetch(self,q,*args):
            return [
                {"bucket":datetime(2026,1,1,tzinfo=timezone.utc),"equity":100.0},
                {"bucket":datetime(2026,1,2,tzinfo=timezone.utc),"equity":90.0},
                {"bucket":datetime(2026,1,3,tzinfo=timezone.utc),"equity":95.0},
            ]
    class Acquire:
        async def __aenter__(self): return Conn()
        async def __aexit__(self,*a): pass
    class Pool:
        def acquire(self): return Acquire()
    svc=DashboardService(Pool(),Cache())
    out=asyncio.run(svc.timeseries("drawdown","PAPER_TESTNET",None,datetime(2026,1,1,tzinfo=timezone.utc),datetime(2026,1,3,tzinfo=timezone.utc),100))
    assert out["points"][0][1] == 0.0
    assert abs(out["points"][1][1] + 0.1) < 1e-12
    assert abs(out["points"][2][1] + 0.05) < 1e-12


def test_equity_query_uses_real_parameter_placeholder(monkeypatch):
    class Cache:
        async def get(self,k): return None
        async def set(self,k,v): pass
    captured=[]
    class Conn:
        async def fetch(self,q,*args):
            captured.append((q,args)); return []
    class Acquire:
        async def __aenter__(self): return Conn()
        async def __aexit__(self,*a): pass
    class Pool:
        def acquire(self): return Acquire()
    svc=DashboardService(Pool(),Cache())
    asyncio.run(svc._equity('PAPER_TESTNET', None, None, '1 hour'))
    assert captured
    assert 'time_bucket($2, ts)' in captured[0][0]
    assert captured[0][1] == ('PAPER_TESTNET', '1 hour')

def test_live_confirmation_is_rendered_and_wired():
    text=open('frontend/src/main.jsx').read()
    assert "pendingMode === 'LIVE'" in text
    assert "onConfirm={()=>{setMode('LIVE');setPendingMode(null)}}" in text

def test_account_snapshot_schema_has_positions():
    text=open('sql/007_p2_dashboard_telemetry.sql').read()
    assert 'positions JSONB' in text
    assert 'ADD COLUMN IF NOT EXISTS positions JSONB' in text


def test_ws_health_migration_exists():
    text=open('sql/008_dashboard_ws_health.sql').read()
    assert 'dashboard.ws_health' in text
    assert 'connected BOOLEAN' in text
    assert 'last_heartbeat' not in text  # heartbeat timestamp is represented by ts

def test_execution_position_preserves_liquidation_price():
    text=open('app/paper.py').read()
    assert 'liquidation_price: Decimal' in text
    assert 'p.get("liquidationPrice", "0")' in text
