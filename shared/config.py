from datetime import datetime
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    postgres_user: str = "polyarb"
    postgres_password: str = "polyarb_dev"
    postgres_db: str = "polyarb"
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    redis_url: str = "redis://redis:6379/0"
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 384
    gamma_api_base: str = "https://gamma-api.polymarket.com"
    clob_api_base: str = "https://clob.polymarket.com"
    poll_interval_seconds: int = 30
    rate_limit_rps: float = 2.0
    fetch_order_books: bool = False
    max_snapshot_markets: int = 100
    log_level: str = "INFO"

    # WebSocket streaming settings
    ws_enabled: bool = True
    ws_clob_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    ws_reconnect_base_delay: float = 1.0
    ws_reconnect_max_delay: float = 60.0
    ws_ping_interval: int = 10
    ws_snapshot_buffer_seconds: float = 2.0

    # Detector settings
    similarity_threshold: float = 0.82
    similarity_top_k: int = 20
    detector_batch_size: int = 100
    classifier_model: str = "gpt-4.1-mini"
    detection_interval_seconds: int = 60

    # Optimizer settings
    fw_max_iterations: int = 200
    fw_gap_tolerance: float = 0.001
    fw_ip_timeout_ms: int = 5000
    optimizer_interval_seconds: int = 30
    optimizer_min_edge: float = 0.03
    optimizer_skip_conditional: bool = True

    # Simulator settings
    initial_capital: float = 10000.0
    max_position_size: float = 100.0
    slippage_model: str = "vwap"
    simulator_interval_seconds: int = 60
    max_snapshot_age_seconds: int = 120  # Reject price snapshots older than this
    simulator_reset_epoch: Optional[datetime] = None  # Filter dashboard to only show data after this timestamp

    # Settlement settings
    resolution_price_threshold: float = 0.98
    settlement_interval_seconds: int = 120

    # Circuit breaker settings
    cb_max_daily_loss: float = 500.0
    cb_max_position_per_market: float = 200.0
    cb_max_drawdown_pct: float = 10.0
    cb_max_consecutive_errors: int = 5
    cb_cooldown_seconds: int = 300  # 5-minute cooldown

    # Kalshi settings
    kalshi_enabled: bool = False
    kalshi_api_key: str = ""
    kalshi_api_secret: str = ""  # RSA private key (PEM) or path
    kalshi_poll_interval_seconds: int = 120
    kalshi_max_markets: int = 500
    kalshi_rate_limit_rps: float = 1.5

    # Dashboard settings
    dashboard_port: int = 8080

    # Live trading settings (Workstream 2)
    live_trading_enabled: bool = False
    live_trading_dry_run: bool = True
    live_trading_api_key: str = ""
    live_trading_private_key: str = ""
    live_trading_chain_id: int = 137
    live_trading_bankroll: float = 100.0
    live_trading_max_position_size: float = 10.0
    live_trading_scale_factor: float = 0.01
    live_trading_min_edge: float = 0.03
    live_trading_max_daily_loss_pct: float = 10.0

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()


def polymarket_fee(price: float, side: str) -> float:
    """Polymarket taker fee: price * (1 - price) * 0.015.

    The formula is symmetric — the same for BUY and SELL because Polymarket
    charges on the probability of payout, which is price*(1-price) regardless
    of direction. Maker orders pay 0%; we conservatively assume taker.
    """
    return price * (1.0 - price) * 0.015


def venue_fee(venue: str, price: float, side: str = "BUY") -> float:
    """Route fee calculation to the correct venue fee schedule."""
    if venue == "kalshi":
        return kalshi_fee(price)
    return polymarket_fee(price, side)


def kalshi_fee(price: float) -> float:
    """Kalshi fee: ceil(7% of price * (1 - price)) per contract (in cents).

    Returns fee as a fraction of $1 contract (divide cents by 100).
    """
    import math
    fee_cents = math.ceil(7.0 * price * (1.0 - price))
    return fee_cents / 100.0
