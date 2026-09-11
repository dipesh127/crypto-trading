from __future__ import annotations
import time
try:
    from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
except ImportError:
    Counter=Gauge=Histogram=None
    CONTENT_TYPE_LATEST='text/plain; version=0.0.4'

REQUESTS=Counter('dashboard_http_requests_total','HTTP requests',['method','path','status']) if Counter else None
REQUEST_LATENCY=Histogram('dashboard_http_request_duration_seconds','HTTP request latency',['method','path']) if Histogram else None
WS_CLIENTS=Gauge('dashboard_websocket_clients','Connected dashboard WebSocket clients') if Gauge else None
TRADING_RISK_PAUSED=Gauge('trading_risk_paused','Whether risk manager is paused',['mode']) if Gauge else None

def metrics_payload():
    if 'generate_latest' in globals() and generate_latest:
        return generate_latest()
    return b''

def observe_request(method,path,status,elapsed):
    if REQUESTS: REQUESTS.labels(method,path,str(status)).inc()
    if REQUEST_LATENCY: REQUEST_LATENCY.labels(method,path).observe(max(0,float(elapsed)))


ORDERS_TOTAL=Counter('trading_orders_total','Orders submitted',['mode','symbol','side','status']) if Counter else None
FILLS_TOTAL=Counter('trading_fills_total','Executed fills',['mode','symbol','side']) if Counter else None
RISK_VETOES_TOTAL=Counter('trading_risk_vetoes_total','Risk vetoes',['mode','reason']) if Counter else None
REST_ERRORS_TOTAL=Counter('trading_rest_errors_total','Exchange REST errors',['mode','endpoint']) if Counter else None
MARKET_GAPS_TOTAL=Counter('market_data_gaps_total','Detected market data gaps',['symbol','kind']) if Counter else None
WS_RECONNECTS_TOTAL=Counter('market_ws_reconnects_total','Market WebSocket reconnects',['stream']) if Counter else None
INFERENCE_LATENCY=Histogram('model_inference_latency_seconds','Model inference latency',['mode','model']) if Histogram else None
ORDER_LATENCY=Histogram('trading_order_latency_seconds','Order submit to acknowledgement latency',['mode','symbol']) if Histogram else None
UPNL=Gauge('trading_unrealized_pnl','Unrealized PnL',['mode','symbol']) if Gauge else None
EQUITY=Gauge('trading_equity','Account equity',['mode']) if Gauge else None
EXPOSURE=Gauge('trading_exposure_notional','Current notional exposure',['mode']) if Gauge else None
BINANCE_WEIGHT_REMAINING=Gauge('binance_rate_limit_weight_remaining','Binance request-weight tokens remaining') if Gauge else None
BINANCE_ORDERS_REMAINING=Gauge('binance_rate_limit_orders_remaining','Binance order-request tokens remaining') if Gauge else None
BINANCE_RAW_REMAINING=Gauge('binance_rate_limit_raw_remaining','Binance raw-request tokens remaining') if Gauge else None
BINANCE_429_TOTAL=Counter('binance_429_total','Binance HTTP 429 responses') if Counter else None
BINANCE_418_TOTAL=Counter('binance_418_total','Binance HTTP 418 responses') if Counter else None
BINANCE_RATE_LIMIT_STATE={"weight_remaining":None,"orders_remaining":None,"raw_remaining":None,"429_total":0,"418_total":0}

def observe_order(mode,symbol,side,status):
    if ORDERS_TOTAL: ORDERS_TOTAL.labels(mode,symbol,side,status).inc()
def observe_fill(mode,symbol,side):
    if FILLS_TOTAL: FILLS_TOTAL.labels(mode,symbol,side).inc()
def observe_risk_veto(mode,reason):
    if RISK_VETOES_TOTAL: RISK_VETOES_TOTAL.labels(mode,reason).inc()
def observe_rest_error(mode,endpoint):
    if REST_ERRORS_TOTAL: REST_ERRORS_TOTAL.labels(mode,endpoint).inc()
def observe_market_gap(symbol,kind):
    if MARKET_GAPS_TOTAL: MARKET_GAPS_TOTAL.labels(symbol,kind).inc()
def observe_ws_reconnect(stream):
    if WS_RECONNECTS_TOTAL: WS_RECONNECTS_TOTAL.labels(stream).inc()
def observe_inference(mode,model,seconds):
    if INFERENCE_LATENCY: INFERENCE_LATENCY.labels(mode,model).observe(max(0,float(seconds)))
def observe_order_latency(mode,symbol,seconds):
    if ORDER_LATENCY: ORDER_LATENCY.labels(mode,symbol).observe(max(0,float(seconds)))
def set_account_telemetry(mode,equity=None,exposure=None):
    if equity is not None and EQUITY: EQUITY.labels(mode).set(float(equity))
    if exposure is not None and EXPOSURE: EXPOSURE.labels(mode).set(float(exposure))

def set_binance_rate_limit_telemetry(*, weight_remaining=None, orders_remaining=None, raw_remaining=None):
    if weight_remaining is not None: BINANCE_RATE_LIMIT_STATE['weight_remaining']=max(0,float(weight_remaining))
    if orders_remaining is not None: BINANCE_RATE_LIMIT_STATE['orders_remaining']=max(0,float(orders_remaining))
    if raw_remaining is not None: BINANCE_RATE_LIMIT_STATE['raw_remaining']=max(0,float(raw_remaining))
    if weight_remaining is not None and BINANCE_WEIGHT_REMAINING: BINANCE_WEIGHT_REMAINING.set(max(0, float(weight_remaining)))
    if orders_remaining is not None and BINANCE_ORDERS_REMAINING: BINANCE_ORDERS_REMAINING.set(max(0, float(orders_remaining)))
    if raw_remaining is not None and BINANCE_RAW_REMAINING: BINANCE_RAW_REMAINING.set(max(0, float(raw_remaining)))

def observe_binance_http_status(status):
    if int(status) == 429:
        BINANCE_RATE_LIMIT_STATE['429_total']+=1
        if BINANCE_429_TOTAL: BINANCE_429_TOTAL.inc()
    if int(status) == 418:
        BINANCE_RATE_LIMIT_STATE['418_total']+=1
        if BINANCE_418_TOTAL: BINANCE_418_TOTAL.inc()

def binance_rate_limit_state(): return dict(BINANCE_RATE_LIMIT_STATE)

POSITION_UPNL=Gauge('trading_position_unrealized_pnl','Unrealized PnL by position',['mode','symbol']) if Gauge else None
MARGIN_RATIO=Gauge('trading_margin_ratio','Maintenance margin divided by equity',['mode']) if Gauge else None
REST_RATE=Gauge('trading_rest_errors_last_5m','REST errors in recent window',['mode']) if Gauge else None

def set_position_telemetry(mode, positions):
    if not POSITION_UPNL: return
    for p in positions:
        POSITION_UPNL.labels(mode,str(p.get('symbol',''))).set(float(p.get('unrealized_pnl',0) or 0))

def set_margin_ratio(mode, value):
    if MARGIN_RATIO and value is not None: MARGIN_RATIO.labels(mode).set(float(value))

EXECUTION_WS_RECONNECTS=Counter('execution_user_ws_reconnects_total','Authenticated user-data websocket reconnects',['mode']) if Counter else None
MARKET_EVENT_AGE=Gauge('market_data_event_age_seconds','Age of most recently observed market event',['symbol','kind']) if Gauge else None

def observe_user_ws_reconnect(mode):
    if EXECUTION_WS_RECONNECTS: EXECUTION_WS_RECONNECTS.labels(mode).inc()

def observe_market_event_age(symbol,kind,seconds):
    if MARKET_EVENT_AGE: MARKET_EVENT_AGE.labels(symbol,kind).set(max(0,float(seconds)))
