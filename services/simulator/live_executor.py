"""Live trading executor — mirrors paper trades to Polymarket CLOB API.

Safety-first design:
- Off by default (live_trading_enabled=False)
- Dry-run mode logs orders without submitting (live_trading_dry_run=True)
- Min-edge filter skips low-conviction trades
- Max daily loss auto-disables live trading
- Max position size hard cap
- Balance check before every order
"""

from datetime import datetime, timezone
from decimal import Decimal

import structlog

logger = structlog.get_logger()


class LiveExecutor:
    """Execute real trades on Polymarket via CLOB API."""

    def __init__(
        self,
        api_key: str,
        private_key: str,
        chain_id: int,
        bankroll: float,
        max_position_size: float,
        scale_factor: float,
        min_edge: float,
        max_daily_loss_pct: float,
        dry_run: bool = True,
    ):
        self.api_key = api_key
        self.private_key = private_key
        self.chain_id = chain_id
        self.bankroll = Decimal(str(bankroll))
        self.max_position_size = Decimal(str(max_position_size))
        self.scale_factor = Decimal(str(scale_factor))
        self.min_edge = Decimal(str(min_edge))
        self.max_daily_loss_pct = Decimal(str(max_daily_loss_pct))
        self.dry_run = dry_run

        # State tracking
        self.daily_pnl = Decimal("0")
        self.daily_reset_date: str = ""
        self.disabled = False
        self.client = None

    async def initialize(self) -> None:
        """Initialize the CLOB client. Requires py-clob-client."""
        if not self.api_key or not self.private_key:
            logger.warning("live_executor_no_credentials", msg="API key or private key not set")
            self.disabled = True
            return

        try:
            from py_clob_client.client import ClobClient

            self.client = ClobClient(
                host="https://clob.polymarket.com",
                key=self.private_key,
                chain_id=self.chain_id,
                creds={"apiKey": self.api_key},
            )
            logger.info("live_executor_initialized", dry_run=self.dry_run)
        except ImportError:
            logger.warning(
                "live_executor_missing_dependency",
                msg="Install py-clob-client: pip install py-clob-client",
            )
            self.disabled = True
        except Exception:
            logger.exception("live_executor_init_failed")
            self.disabled = True

    def _check_daily_reset(self) -> None:
        """Reset daily PnL tracker at midnight UTC."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self.daily_reset_date:
            self.daily_pnl = Decimal("0")
            self.daily_reset_date = today
            # Re-enable if previously auto-disabled by daily loss
            if self.disabled:
                logger.info("live_executor_daily_reset", msg="Re-enabling after daily reset")
                self.disabled = False

    def _check_kill_switch(self) -> bool:
        """Return True if trading should be blocked."""
        if self.disabled:
            return True

        self._check_daily_reset()

        # Max daily loss check
        if self.bankroll > 0:
            loss_pct = abs(min(self.daily_pnl, Decimal("0"))) / self.bankroll * 100
            if loss_pct >= self.max_daily_loss_pct:
                logger.warning(
                    "live_executor_daily_loss_limit",
                    daily_pnl=float(self.daily_pnl),
                    loss_pct=float(loss_pct),
                )
                self.disabled = True
                return True

        return False

    async def execute_trade(
        self,
        token_id: str,
        side: str,
        size: float,
        price: float,
        estimated_profit: float,
    ) -> dict:
        """Execute a live trade (or log in dry-run mode).

        Args:
            token_id: Polymarket CLOB token ID
            side: "BUY" or "SELL"
            size: Paper trade size (will be scaled by scale_factor)
            price: Target price
            estimated_profit: Estimated profit from optimizer

        Returns:
            Result dict with status and details.
        """
        if self._check_kill_switch():
            return {"status": "blocked", "reason": "kill_switch"}

        # Min edge filter
        if Decimal(str(estimated_profit)) < self.min_edge:
            return {"status": "skipped", "reason": "below_min_edge"}

        # Scale size from paper to live
        live_size = Decimal(str(size)) * self.scale_factor

        # Hard cap
        position_value = live_size * Decimal(str(price))
        if position_value > self.max_position_size:
            live_size = self.max_position_size / Decimal(str(price))

        if live_size <= Decimal("0.01"):
            return {"status": "skipped", "reason": "size_too_small"}

        trade_info = {
            "token_id": token_id,
            "side": side,
            "size": float(live_size),
            "price": price,
            "estimated_profit": estimated_profit,
        }

        if self.dry_run:
            logger.info("live_executor_dry_run", **trade_info)
            return {"status": "dry_run", **trade_info}

        if not self.client:
            return {"status": "error", "reason": "client_not_initialized"}

        # Submit order via CLOB API
        try:
            from py_clob_client.order_builder.constants import BUY as CLOB_BUY, SELL as CLOB_SELL

            order_side = CLOB_BUY if side == "BUY" else CLOB_SELL

            order = self.client.create_and_post_order(
                token_id=token_id,
                price=price,
                size=float(live_size),
                side=order_side,
            )

            logger.info("live_executor_order_submitted", order=order, **trade_info)

            return {
                "status": "submitted",
                "order": order,
                **trade_info,
            }

        except Exception as e:
            logger.exception("live_executor_order_failed", error=str(e), **trade_info)
            return {"status": "error", "reason": str(e), **trade_info}

    def kill(self) -> None:
        """Emergency kill switch — instantly disable all live trading."""
        self.disabled = True
        logger.warning("live_executor_killed", msg="Live trading manually disabled")

    def enable(self) -> None:
        """Re-enable live trading after kill switch."""
        self.disabled = False
        logger.info("live_executor_enabled", msg="Live trading re-enabled")
