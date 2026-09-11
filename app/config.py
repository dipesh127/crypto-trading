from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_env: str = "testnet"
    log_level: str = "INFO"
    binance_rest_base_url: str = "https://testnet.binancefuture.com"
    binance_ws_base_url: str = "wss://stream.binancefuture.com"
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_recv_window_ms: int = 5000
    binance_raw_requests_per_minute: int = 1200
    binance_order_requests_per_minute: int = 1200
    binance_weight_per_minute: int = 2400
    symbols: str = "BTCUSDT,ETHUSDT"
    kline_intervals: str = "1m,3m,5m,15m,1h,4h,1d"
    orderbook_depth_limit: int = 1000
    orderbook_buffer_max: int = 10000
    max_clock_skew_ms: int = 1000
    paper_reconciliation_interval_seconds: int = 30
    paper_testnet_only: bool = True
    live_trading_enabled: bool = False
    live_human_signoff: bool = False
    binance_ip_whitelisted: bool = False
    binance_withdrawals_disabled: bool = True
    postgres_dsn: str = "postgresql://trader:trader@localhost:5432/crypto_rl"
    redis_url: str = "redis://localhost:6379/0"
    raw_retention_days: int = 60
    archive_after_days: int = 60
    archive_dir: str = "data/archive"
    retrain_state_path: str = "data/retrain_schedule.json"
    historical_backfill_days: int = 90
    backfill_batch_limit: int = 1000
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook_url: str = ""
    live_sharpe_baseline: float | None = None
    cdn_bucket: str = ""
    cloudfront_distribution_id: str = ""
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")
    @property
    def symbol_list(self): return [x.strip().upper() for x in self.symbols.split(",") if x.strip()]
    @property
    def interval_list(self): return [x.strip() for x in self.kline_intervals.split(",") if x.strip()]

@lru_cache
def get_settings(): return Settings()
