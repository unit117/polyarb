from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    postgres_user: str = "polyarb"
    postgres_password: str = "changeme"
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

    # Detector settings
    similarity_threshold: float = 0.82
    similarity_top_k: int = 20
    detector_batch_size: int = 100
    classifier_model: str = "gpt-4o-mini"
    detection_interval_seconds: int = 60

    # Optimizer settings
    fw_max_iterations: int = 200
    fw_gap_tolerance: float = 0.001
    fw_ip_timeout_ms: int = 5000
    optimizer_interval_seconds: int = 30
    optimizer_min_edge: float = 0.03
    optimizer_skip_conditional: bool = False

    # Simulator settings
    initial_capital: float = 10000.0
    max_position_size: float = 100.0
    fee_rate: float = 0.02
    slippage_model: str = "vwap"
    simulator_interval_seconds: int = 60

    # Settlement settings
    resolution_price_threshold: float = 0.98
    settlement_interval_seconds: int = 120

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
