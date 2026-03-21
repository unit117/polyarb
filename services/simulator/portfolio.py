"""Portfolio state management for paper trading."""

from decimal import Decimal

import structlog

logger = structlog.get_logger()


class Portfolio:
    """In-memory portfolio state, periodically persisted to DB."""

    def __init__(self, initial_capital: float):
        self.initial_capital = Decimal(str(initial_capital))
        self.cash = Decimal(str(initial_capital))
        self.positions: dict[str, Decimal] = {}  # "market_id:outcome" -> shares
        self.cost_basis: dict[str, Decimal] = {}  # "market_id:outcome" -> total cost paid
        self.realized_pnl = Decimal("0")
        self.total_trades = 0
        self.winning_trades = 0
        self.settled_trades = 0

    def execute_trade(
        self,
        market_id: int,
        outcome: str,
        side: str,
        size: float,
        vwap_price: float,
        fees: float,
    ) -> dict:
        """Execute a paper trade and update portfolio state.

        Returns trade result dict.
        """
        size_d = Decimal(str(size))
        price_d = Decimal(str(vwap_price))
        fees_d = Decimal(str(fees))
        key = f"{market_id}:{outcome}"

        if side == "BUY":
            cost = size_d * price_d + fees_d
            if cost > self.cash:
                # Reduce size to fit available capital
                max_size = (self.cash - fees_d) / price_d
                if max_size <= 0:
                    return {"executed": False, "reason": "insufficient_capital"}
                size_d = max_size.quantize(Decimal("0.01"))
                cost = size_d * price_d + fees_d

            self.cash -= cost
            self.positions[key] = self.positions.get(key, Decimal("0")) + size_d
            self.cost_basis[key] = self.cost_basis.get(key, Decimal("0")) + size_d * price_d

        else:  # SELL
            current = self.positions.get(key, Decimal("0"))
            sell_size = min(size_d, current) if current > 0 else size_d
            proceeds = sell_size * price_d - fees_d
            self.cash += proceeds

            if current > 0:
                # Closing/reducing a long — reduce cost basis proportionally
                if key in self.cost_basis:
                    avg_entry = self.cost_basis[key] / current
                    self.cost_basis[key] -= sell_size * avg_entry

                self.positions[key] = current - sell_size
                if self.positions[key] <= 0:
                    del self.positions[key]
                    self.cost_basis.pop(key, None)
            else:
                # Opening/increasing a short — cost basis tracks credit received
                self.positions[key] = current - sell_size
                self.cost_basis[key] = self.cost_basis.get(key, Decimal("0")) + sell_size * price_d

        self.total_trades += 1

        logger.info(
            "trade_executed",
            market_id=market_id,
            outcome=outcome,
            side=side,
            size=float(size_d),
            price=float(price_d),
            cash_remaining=float(self.cash),
        )

        return {
            "executed": True,
            "size": float(size_d),
            "price": float(price_d),
            "fees": float(fees_d),
            "cash_remaining": float(self.cash),
        }

    def close_position(self, key: str, settlement_price: float) -> dict:
        """Close a position at a known settlement price.

        For market resolution: settlement_price = 1.0 (winning outcome) or 0.0 (losing).
        For rebalancing exits: settlement_price = current market price.
        """
        if key not in self.positions:
            return {"closed": False, "reason": "no_position"}

        shares = self.positions[key]
        cost = self.cost_basis.get(key, Decimal("0"))

        if shares > 0:
            # Long: payout = shares * price, pnl = payout - cost
            payout = shares * Decimal(str(settlement_price))
            pnl = payout - cost
            self.cash += payout
        else:
            # Short: obligation = |shares| * price, pnl = credit_received - obligation
            obligation = abs(shares) * Decimal(str(settlement_price))
            pnl = cost - obligation
            self.cash -= obligation

        self.realized_pnl += pnl
        self.settled_trades += 1

        if pnl > 0:
            self.winning_trades += 1

        del self.positions[key]
        self.cost_basis.pop(key, None)

        logger.info(
            "position_closed",
            key=key,
            shares=float(shares),
            settlement_price=settlement_price,
            pnl=float(pnl),
        )

        return {
            "closed": True,
            "key": key,
            "shares": float(shares),
            "settlement_price": settlement_price,
            "pnl": float(pnl),
            "is_winner": pnl > 0,
        }

    def mark_settled(self, is_winner: bool = False) -> None:
        """Record a settled/closed trade for win-rate tracking."""
        self.settled_trades += 1
        if is_winner:
            self.winning_trades += 1

    def total_value(self, current_prices: dict[str, float] | None = None) -> float:
        """Compute total portfolio value (cash + positions at market)."""
        pos_value = Decimal("0")
        if current_prices:
            for key, shares in self.positions.items():
                price = Decimal(str(current_prices.get(key, 0)))
                pos_value += shares * price
        return float(self.cash + pos_value)

    def unrealized_pnl(self, current_prices: dict[str, float] | None = None) -> float:
        """Compute unrealized PnL from open positions using tracked cost basis."""
        if not current_prices:
            return 0.0
        pnl = Decimal("0")
        for key, shares in self.positions.items():
            current = Decimal(str(current_prices.get(key, 0)))
            cost = self.cost_basis.get(key, abs(shares) * Decimal("0.5"))
            if shares > 0:
                pnl += shares * current - cost
            else:
                # Short: profit = credit received - cost to close
                pnl += cost - abs(shares) * current
        return float(pnl)

    def positions_in_profit(self, current_prices: dict[str, float] | None = None) -> tuple[int, int]:
        """Return (positions_in_profit, total_positions) using cost basis."""
        total = len(self.positions)
        if not current_prices or total == 0:
            return 0, total
        in_profit = 0
        for key, shares in self.positions.items():
            current = Decimal(str(current_prices.get(key, 0)))
            cost = self.cost_basis.get(key, abs(shares) * Decimal("0.5"))
            if shares > 0:
                profitable = shares * current > cost
            else:
                # Short: profitable when cost to close < credit received
                profitable = abs(shares) * current < cost
            if profitable:
                in_profit += 1
        return in_profit, total

    def to_snapshot_dict(self, current_prices: dict[str, float] | None = None) -> dict:
        tv = self.total_value(current_prices)
        upnl = self.unrealized_pnl(current_prices)
        in_profit, total_pos = self.positions_in_profit(current_prices)
        return {
            "cash": float(self.cash),
            "positions": {k: float(v) for k, v in self.positions.items()},
            "cost_basis": {k: float(v) for k, v in self.cost_basis.items()},
            "total_value": tv,
            "realized_pnl": float(self.realized_pnl),
            "unrealized_pnl": upnl,
            "total_trades": self.total_trades,
            "settled_trades": self.settled_trades,
            "winning_trades": self.winning_trades,
            "positions_in_profit": in_profit,
            "total_positions": total_pos,
        }
