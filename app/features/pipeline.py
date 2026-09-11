from __future__ import annotations
import json, hashlib
import pandas as pd
from .indicators import *
from .regime import regime_inputs, MarketRegimeClassifier
from .cross_asset import btc_correlation, btc_beta, cross_sectional_features

FEATURE_CODE_VERSION='phase2-features-v1.3.0'

class FeaturePipeline:
    def __init__(self, windows=None, regime_classifier=None, regime_window=20, n_regimes=4, regime_method='kmeans', decision_lag=1):
        self.windows=windows or {'vol':20,'rsi':14,'atr':14,'bb':20,'stoch':14,'cci':20,'roc':12,'willr':14,'hurst':100,'skew':20,'kurt':20,'cmf':20,'adf':100,'autocorr':60,'depth_bps':20,'trade_intensity':60}
        self.regime_window=int(regime_window); self.decision_lag=int(max(0,decision_lag))
        self.regime_classifier=regime_classifier or MarketRegimeClassifier(n_regimes=n_regimes, method=regime_method)
        self.regime_fitted=False

    def fit_regime(self, df):
        x=regime_inputs(df['close'],df['high'],df['low'],df['volume'],self.regime_window)
        self.regime_classifier.fit(x)
        self.regime_fitted=True
        return self

    def compute(self, df, *, fit_regime=True, trade_events=None, btc_close=None, cross_asset_frames=None, cross_window=60):
        d=df.copy(); required={'open','high','low','close','volume'}
        missing=required-set(d.columns)
        if missing: raise ValueError(f'missing columns: {sorted(missing)}')
        w=self.windows; out=pd.DataFrame(index=d.index)
        out['simple_return']=simple_returns(d.close); out['log_return']=log_returns(d.close); out['rolling_volatility']=rolling_volatility(d.close,w['vol']); out['zscore_close']=zscore(d.close,w['vol']); out['minmax_close']=minmax(d.close,w['vol']); out['sma']=sma(d.close,w['vol']); out['ema']=ema(d.close,w['vol'])
        out=out.join(macd(d.close));
        ichi_c=ichimoku(d.high,d.low,d.close,representation='causal'); out=out.join(ichi_c)
        ichi_t=ichimoku(d.high,d.low,d.close,representation='traditional').add_suffix('_traditional'); out=out.join(ichi_t)
        out=out.join(adx(d.high,d.low,d.close,w['atr'])); out=out.join(stochastic(d.high,d.low,d.close,w['stoch'])); out['rsi']=rsi(d.close,w['rsi']); out['cci']=cci(d.high,d.low,d.close,w['cci']); out['roc']=roc(d.close,w['roc']); out['williams_r']=williams_r(d.high,d.low,d.close,w['willr']); out=out.join(bollinger(d.close,w['bb'])); out['atr']=atr(d.high,d.low,d.close,w['atr']); out=out.join(keltner(d.high,d.low,d.close,w['vol'],w['atr'])); out['obv']=obv(d.close,d.volume); out['vwap']=vwap(d.high,d.low,d.close,d.volume)
        if 'taker_buy_base_volume' in d: out['cvd']=cvd(d.taker_buy_base_volume,d.volume)
        if {'bid_qty','ask_qty'}<=set(d): out['obi']=order_book_imbalance(d.bid_qty,d.ask_qty)
        if {'bid_price','ask_price','bid_qty','ask_qty'}<=set(d): out['microprice']=microprice(d.bid_price,d.ask_price,d.bid_qty,d.ask_qty); out=out.join(spread(d.bid_price,d.ask_price)); out['ofi']=ofi(d.bid_price,d.ask_price,d.bid_qty,d.ask_qty)
        if {'price','signed_volume'}<=set(d): out['kyles_lambda']=kyles_lambda(d.price,d.signed_volume)
        if 'funding_rate' in d: out['funding_rate']=d.funding_rate; out['funding_roc']=funding_roc(d.funding_rate)
        if {'spot_price','futures_price'}<=set(d): out['basis']=basis(d.spot_price,d.futures_price)
        if 'open_interest' in d: out['oi_price_quadrant']=oi_price_quadrant(d.open_interest,d.close); out['oi_momentum']=d.open_interest.pct_change(w['vol'])
        if {'liq_long','liq_short'}<=set(d): out=out.join(liquidation_cluster(d.liq_long,d.liq_short,w['vol']))
        out['hurst_rs']=hurst_rs(d.close,w['hurst']); out['rolling_skew']=rolling_skew(out['log_return'],w['skew']); out['rolling_kurtosis']=rolling_kurtosis(out['log_return'],w['kurt'])
        out['cmf']=chaikin_money_flow(d.high,d.low,d.close,d.volume,w['cmf'])
        out['adf_statistic']=adf_statistic(d.close,w['adf'])
        out['return_autocorrelation_1']=rolling_return_autocorrelation(d.close,1,w['autocorr'])
        out['return_autocorrelation_5']=rolling_return_autocorrelation(d.close,5,w['autocorr'])
        if {'bid_prices','bid_qtys','ask_prices','ask_qtys'}<=set(d):
            dep=depth_within_bps(d.bid_prices,d.bid_qtys,d.ask_prices,d.ask_qtys,bps=(1,5,10,25,50))
            dep.index=d.index; out=out.join(dep)
        elif {'bid_price','ask_price','bid_qty','ask_qty'}<=set(d):
            dep=depth_within_bps(d.bid_price,d.bid_qty,d.ask_price,d.ask_qty,bps=(1,5,10,25,50))
            dep.index=d.index; out=out.join(dep)
        if trade_events is not None:
            out['trade_intensity']=agg_trade_intensity(d.index,trade_events,decay_seconds=float(w['trade_intensity']))
        elif 'event_time' in d.columns:
            raise ValueError('event_time in OHLCV is not sufficient for aggTrade intensity; pass trade_events explicitly')

        if fit_regime and not self.regime_fitted:
            self.fit_regime(d)
        if not self.regime_fitted:
            raise RuntimeError('regime classifier is not fitted; fit it on training data and load the persisted state for validation/live inference')
        regime_x=regime_inputs(d['close'],d['high'],d['low'],d['volume'],self.regime_window)
        out['regime_label']=self.regime_classifier.predict(regime_x).astype('float64')
        # Strict decision-time convention: row t only exposes information from completed rows <= t-1.
        return out.shift(self.decision_lag) if self.decision_lag else out

    def compute_multitimeframe(self, frames:dict[str,pd.DataFrame], *, fit_regime=True, trade_events=None):
        pieces=[]
        for tf,df in frames.items():
            f=self.compute(df, fit_regime=fit_regime, trade_events=trade_events); f.columns=[f'{c}_{tf}' for c in f.columns]; pieces.append(f)
        return pd.concat(pieces,axis=1).sort_index()

    def compute_cross_asset(self, frames:dict[str,pd.DataFrame], *, btc_symbol='BTCUSDT', window=60, fit_regime=True):
        """Compute per-symbol features plus BTC correlation/beta and cross-sectional ranks."""
        if not frames: raise ValueError('frames cannot be empty')
        btc_key=next((k for k in frames if k.upper()==btc_symbol.upper()), None)
        btc=frames[btc_key]['close'] if btc_key else None
        xs=cross_sectional_features(frames, window=max(5, min(window, 20)))
        if fit_regime and not self.regime_fitted:
            self.fit_regime(next(iter(frames.values())))
        out={}
        for symbol, df in frames.items():
            f=self.compute(df, fit_regime=False)
            if btc is not None and symbol.upper()!=btc_symbol.upper():
                f['btc_correlation']=btc_correlation(df['close'],btc,window)
                f['btc_beta']=btc_beta(df['close'],btc,window)
            for name, table in xs.items():
                if symbol in table.columns: f[f'xs_{name}']=table[symbol].reindex(f.index)
            out[symbol]=f
        return out

    def save_regime(self, path):
        from .checkpoint import save_regime_state
        return save_regime_state(path,self.regime_classifier)

    def load_regime(self, path):
        from .checkpoint import load_regime_state
        self.regime_classifier=load_regime_state(path); self.regime_fitted=True
        return self

def schema_hash(columns): return hashlib.sha256(json.dumps(list(columns),sort_keys=True).encode()).hexdigest()

def write_feature_manifest(path, columns, scaler_state=None, extra=None):
    manifest={'feature_code_version':FEATURE_CODE_VERSION,'schema_hash':schema_hash(columns),'columns':list(columns),'scaler':scaler_state,'extra':extra or {}}
    with open(path,'w',encoding='utf-8') as f: json.dump(manifest,f,indent=2,sort_keys=True)
    return manifest

