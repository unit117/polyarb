from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

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
    classifier_base_url: str = ""  # empty = OpenAI direct; set for any OpenAI-compatible provider
    classifier_api_key: str = ""  # optional provider-specific key for classifier traffic
    classifier_prompt_adapter: Literal["auto", "openai_generic", "claude_xml"] = "auto"
    # JSON override for the per-model capability registry (pattern -> partial
    # fields), so a new provider quirk is a .env edit instead of a code
    # hotfix. See services/detector/model_capabilities.py for the format.
    classifier_model_capabilities: str = ""
    # Per-request LLM timeout. App-level retry owns retries (max_retries=0 on
    # the client); 60s covers reasoning-model vector calls (2048-token budgets)
    # that a 30s cap would chronically abort into 3x retry amplification.
    classifier_timeout_seconds: float = 60.0
    # After this many CONSECUTIVE post-retry LLM failures within one detection
    # cycle, skip LLM classification for the cycle's remaining candidates
    # (rule-based and cached classification still run). Bounds lock-held time
    # during a sustained provider outage. 0 disables.
    classifier_cycle_failure_budget: int = 3
    openrouter_api_key: str = ""  # legacy fallback for OpenRouter-based classifier routing
    shadow_classifier_model: str = ""  # for shadow mode comparison (e.g. minimax/minimax-m2.7)
    shadow_classifier_base_url: str = ""
    detection_interval_seconds: int = 60

    # Uncertainty filter — reject near-resolved markets in detector
    uncertainty_price_floor: float = 0.05
    uncertainty_price_ceil: float = 0.95

    # Dormant-pair filter — stop re-creating opportunities for pairs that keep
    # optimizing to zero executable profit (theoretical edge but no real edge),
    # which otherwise recycle ~1/min. A pair goes dormant when its last
    # dormant_pair_min_evaluations optimized opps within the window were all
    # zero-profit; it re-probes automatically once the window empties.
    dormant_pair_enabled: bool = True
    dormant_pair_min_evaluations: int = 5
    dormant_pair_window_seconds: int = 1800

    # Optimizer settings
    fw_max_iterations: int = 200
    fw_gap_tolerance: float = 0.001
    fw_ip_timeout_ms: int = 5000
    optimizer_interval_seconds: int = 30
    optimizer_min_edge: float = 0.03
    optimizer_skip_conditional: bool = True
    optimizer_max_snapshot_age_seconds: int = 900  # Optimizer tolerates older prices (15 min)

    # Position sizing
    kelly_multiplier: float = 0.5  # Half-Kelly
    kelly_fraction_cap: float = 0.25  # Max Kelly fraction (backtest overrides to 1.0)

    # Slippage estimation
    base_slippage_rate: float = 0.005  # 0.5% VWAP midpoint fallback + optimizer proxy
    max_slippage_cap: float = 0.05  # 5% ceiling

    # Edge / profit thresholds
    max_edge_sanity: float = 0.20  # Reject edges above this as misclassification
    min_net_profit: float = 0.005  # Minimum net profit after fees+slippage

    # Simulator settings
    initial_capital: float = 10000.0
    max_position_size: float = 100.0
    slippage_model: str = "vwap"
    simulator_interval_seconds: int = 60
    max_snapshot_age_seconds: int = 600  # Reject price snapshots older than this (10 min)
    max_opportunity_retries: int = 10  # Expire opportunity after this many blocked attempts
    # Post-restart grace: for this long after simulator boot, only trade
    # markets whose latest snapshot was written AFTER boot. Pre-restart
    # snapshots can be minutes old (passing max_snapshot_age_seconds) while
    # the market moved during the outage — the daily NAS power-cycle showed
    # every service cold-starting against pre-reboot quotes. Keep >=
    # max_snapshot_age_seconds: a shorter grace leaves pre-boot snapshots
    # tradeable between grace expiry and the age gate. 0 disables.
    simulator_startup_grace_seconds: int = 600
    # Per-pair exposure-opening flow cap: total dollars of NEW exposure
    # (longs bought or shorts sold) a single pair may open within the rolling
    # window. Bounds concentration — one pair recycling capital through
    # buy/settle or sell/settle loops can otherwise dominate cash flow
    # (pair 53507 reached ~20% of net flow via 188 short-opening SELLs).
    # 0 disables. Calibration 2026-07-21: 7-day per-pair flows topped out
    # at ~$112; $100 ≈ 1% of capital binds outliers without touching the
    # typical pair (<= $42/week).
    max_pair_weekly_flow: float = 100.0
    pair_flow_window_seconds: int = 604800  # 7 days
    # Frozen-price guard: reject trades whose quoted midpoint has not moved
    # across recent snapshots. A frozen price means an illiquid/stale market
    # whose "edge" is not actually tradeable; without this, the same opportunity
    # recurs every cycle and the simulator re-enters, silently accumulating a
    # directional position on dead data.
    reject_frozen_prices: bool = True
    price_staleness_window_seconds: int = 3600  # look-back window for price movement
    price_staleness_min_observations: int = 4  # snapshots needed in window to judge frozen
    # Frozen-pair cooldown: after this many frozen-price rejections within the
    # rolling window, the pair is cooled — the detector stops re-creating its
    # opportunities and the ingestor drops it from the opportunity-based
    # poll-inclusion rule. The frozen guard above only blocks the trade;
    # without this, nothing upstream learns the pair is dead and the same
    # opportunity recycles detect→optimize→reject every few seconds for days.
    frozen_pair_reject_threshold: int = 5
    frozen_pair_reject_window_seconds: int = 1800
    frozen_pair_cooldown_seconds: int = 14400  # 4h; a revived market re-enters via WS
    # Valuation staleness bound: positions whose latest snapshot is older than
    # this are marked at cost basis (break-even) instead of the frozen last
    # price. Execution freshness (max_snapshot_age_seconds) is stricter;
    # valuation tolerates more lag, but beyond this the mark is fiction and
    # feeds phantom PnL into snapshots, drawdown trips, and Kelly scaling.
    valuation_max_snapshot_age_seconds: int = 3600
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
    live_trading_signature_type: int = 0
    live_trading_funder: str = ""
    live_trading_bankroll: float = 100.0
    live_trading_max_position_size: float = 10.0
    live_trading_min_edge: float = 0.03
    live_trading_max_daily_loss_pct: float = 10.0
    live_snapshot_interval_seconds: int = 300
    live_status_heartbeat_seconds: int = 30
    live_reconcile_interval_seconds: int = 5

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

# Drawdown scaling constants — shared between live and backtest.
# Mathematically coupled: scaling kicks in at DRAWDOWN_THRESHOLD,
# ramps linearly over DRAWDOWN_WINDOW, floors at DRAWDOWN_MIN_SCALE.
DRAWDOWN_THRESHOLD = 0.05  # Start scaling down Kelly at 5% drawdown
DRAWDOWN_WINDOW = 0.10  # Scale linearly over the next 10%
DRAWDOWN_MIN_SCALE = 0.5  # Floor: never scale below 50%


def polymarket_fee(price: float, side: str = "BUY", fee_rate_bps: int | None = None) -> float:
    """Polymarket taker fee: price * (1 - price) * (fee_rate_bps / 10000).

    The formula is symmetric — the same for BUY and SELL because Polymarket
    charges on the probability of payout, which is price*(1-price) regardless
    of direction. Maker orders pay 0%; we conservatively assume taker.

    fee_rate_bps: per-token rate from CLOB API. Most markets are 0 bps
    (free); some categories charge 1000 bps (10%).
    Falls back to 150 bps if unknown (market not yet synced).
    """
    rate = (fee_rate_bps if fee_rate_bps is not None else 150) / 10_000
    return price * (1.0 - price) * rate


def venue_fee(venue: str, price: float, side: str = "BUY", fee_rate_bps: int | None = None) -> float:
    """Route fee calculation to the correct venue fee schedule."""
    if venue == "kalshi":
        return kalshi_fee(price)
    return polymarket_fee(price, side, fee_rate_bps=fee_rate_bps)


def kalshi_fee(price: float) -> float:
    """Kalshi fee: ceil(7% of price * (1 - price)) per contract (in cents).

    Returns fee as a fraction of $1 contract (divide cents by 100).
    """
    import math
    fee_cents = math.ceil(7.0 * price * (1.0 - price))
    return fee_cents / 100.0
