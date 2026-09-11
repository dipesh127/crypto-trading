import asyncio
from decimal import Decimal
from app.paper import ExecutionState, InternalPosition, BinancePaperExecutionAdapter
from app.reconciliation import Reconciler


def test_execution_state_order_and_account_updates():
    s=ExecutionState()
    s.apply_order_update({'E':10,'o':{'s':'BTCUSDT','c':'cid','S':'BUY','o':'MARKET','q':'0.01','i':7,'X':'FILLED','z':'0.01','ap':'100'}})
    assert s.orders['cid'].status=='FILLED'
    s.apply_account_update({'E':11,'a':{'P':[{'s':'BTCUSDT','pa':'0.01','ep':'100','mp':'101','up':'0.01','iw':'10','mt':'ISOLATED','l':'10'}]}})
    assert s.positions['BTCUSDT'].position_amt == Decimal('0.01')


def test_paper_adapter_refuses_non_testnet():
    class R: base_url='https://fapi.binance.com'
    try: BinancePaperExecutionAdapter(R())
    except ValueError: return
    assert False


def test_reconciliation_detects_position_mismatch():
    class Rest:
        async def position_risk(self): return [{'symbol':'BTCUSDT','positionAmt':'0.2','entryPrice':'100'}]
        async def open_orders(self,symbol): return []
    class Ex: pass
    ex=Ex(); ex.rest=Rest(); ex.state=ExecutionState(); ex.state.positions['BTCUSDT']=InternalPosition('BTCUSDT',Decimal('0.1'))
    result=asyncio.run(Reconciler(ex).check(['BTCUSDT']))
    assert not result['ok'] and result['mismatches'][0]['kind']=='POSITION_QTY'

def test_phase5_migration_contains_shared_execution_schema():
    from pathlib import Path
    sql=Path('sql/002_execution.sql').read_text()
    assert 'execution.orders' in sql and 'execution.fills' in sql
    assert 'mode TEXT NOT NULL' in sql
    assert 'PAPER_TESTNET' not in sql or 'mode' in sql
