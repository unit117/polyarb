"""Tests for Portfolio state management."""

from decimal import Decimal

import pytest

from services.simulator.portfolio import Portfolio


class TestPortfolioInit:
    def test_initial_state(self):
        p = Portfolio(10000.0)
        assert p.cash == Decimal("10000.0")
        assert p.positions == {}
        assert p.cost_basis == {}
        assert p.realized_pnl == Decimal("0")
        assert p.total_trades == 0


class TestExecuteTrade:
    def test_buy_deducts_cash(self):
        p = Portfolio(10000.0)
        result = p.execute_trade(1, "Yes", "BUY", 100, 0.60, 0.009)
        assert result["executed"] is True
        assert result["size"] == 100
        assert float(p.cash) == pytest.approx(10000 - 100 * 0.60 - 0.009, abs=0.01)
        assert float(p.positions["1:Yes"]) == pytest.approx(100.0)

    def test_buy_tracks_cost_basis(self):
        p = Portfolio(10000.0)
        p.execute_trade(1, "Yes", "BUY", 100, 0.60, 0.0)
        assert float(p.cost_basis["1:Yes"]) == pytest.approx(60.0)

    def test_buy_insufficient_capital_reduces_size(self):
        p = Portfolio(50.0)
        result = p.execute_trade(1, "Yes", "BUY", 100, 0.60, 0.0)
        assert result["executed"] is True
        assert result["size"] < 100  # Reduced to fit capital

    def test_buy_insufficient_capital_zero(self):
        p = Portfolio(0.0)
        result = p.execute_trade(1, "Yes", "BUY", 100, 0.60, 0.0)
        assert result["executed"] is False
        assert result["reason"] == "insufficient_capital"

    def test_sell_closing_long(self):
        p = Portfolio(10000.0)
        p.execute_trade(1, "Yes", "BUY", 100, 0.50, 0.0)
        cash_after_buy = float(p.cash)
        p.execute_trade(1, "Yes", "SELL", 100, 0.70, 0.0)
        # Proceeds: 100 * 0.70 = 70
        assert float(p.cash) == pytest.approx(cash_after_buy + 70.0)
        assert "1:Yes" not in p.positions

    def test_sell_partial_close_updates_cost_basis(self):
        p = Portfolio(10000.0)
        p.execute_trade(1, "Yes", "BUY", 100, 0.50, 0.0)
        p.execute_trade(1, "Yes", "SELL", 50, 0.60, 0.0)
        # Remaining: 50 shares, cost basis = 50 * 0.50 = 25
        assert float(p.positions["1:Yes"]) == pytest.approx(50.0)
        assert float(p.cost_basis["1:Yes"]) == pytest.approx(25.0)

    def test_sell_opens_short(self):
        p = Portfolio(10000.0)
        p.execute_trade(1, "Yes", "SELL", 50, 0.60, 0.0)
        assert float(p.positions["1:Yes"]) == pytest.approx(-50.0)
        # Short cost basis = credit received
        assert float(p.cost_basis["1:Yes"]) == pytest.approx(30.0)

    def test_multiple_buys_accumulate(self):
        p = Portfolio(10000.0)
        p.execute_trade(1, "Yes", "BUY", 50, 0.50, 0.0)
        p.execute_trade(1, "Yes", "BUY", 50, 0.60, 0.0)
        assert float(p.positions["1:Yes"]) == pytest.approx(100.0)
        assert float(p.cost_basis["1:Yes"]) == pytest.approx(55.0)  # 25 + 30

    def test_trade_count_increments(self):
        p = Portfolio(10000.0)
        p.execute_trade(1, "Yes", "BUY", 10, 0.50, 0.0)
        p.execute_trade(1, "Yes", "SELL", 10, 0.60, 0.0)
        assert p.total_trades == 2


class TestClosePosition:
    def test_close_long_winner(self):
        p = Portfolio(10000.0)
        p.execute_trade(1, "Yes", "BUY", 100, 0.50, 0.0)
        result = p.close_position("1:Yes", 1.0)
        assert result["closed"] is True
        assert result["pnl"] == pytest.approx(50.0)  # 100*1.0 - 100*0.50
        assert result["is_winner"] is True
        assert p.winning_trades == 1

    def test_close_long_loser(self):
        p = Portfolio(10000.0)
        p.execute_trade(1, "Yes", "BUY", 100, 0.50, 0.0)
        result = p.close_position("1:Yes", 0.0)
        assert result["pnl"] == pytest.approx(-50.0)
        assert result["is_winner"] is False

    def test_close_short_winner(self):
        p = Portfolio(10000.0)
        p.execute_trade(1, "Yes", "SELL", 100, 0.60, 0.0)
        result = p.close_position("1:Yes", 0.0)
        # Short: pnl = credit - obligation = 60 - 0 = 60
        assert result["pnl"] == pytest.approx(60.0)
        assert result["is_winner"] is True

    def test_close_short_loser(self):
        p = Portfolio(10000.0)
        p.execute_trade(1, "Yes", "SELL", 100, 0.60, 0.0)
        result = p.close_position("1:Yes", 1.0)
        # Short: pnl = credit - obligation = 60 - 100 = -40
        assert result["pnl"] == pytest.approx(-40.0)
        assert result["is_winner"] is False

    def test_close_nonexistent(self):
        p = Portfolio(10000.0)
        result = p.close_position("99:Yes", 1.0)
        assert result["closed"] is False

    def test_close_removes_position(self):
        p = Portfolio(10000.0)
        p.execute_trade(1, "Yes", "BUY", 100, 0.50, 0.0)
        p.close_position("1:Yes", 1.0)
        assert "1:Yes" not in p.positions
        assert "1:Yes" not in p.cost_basis


class TestTotalValue:
    def test_cash_only(self):
        p = Portfolio(10000.0)
        assert p.total_value() == pytest.approx(10000.0)

    def test_with_positions(self):
        p = Portfolio(10000.0)
        p.execute_trade(1, "Yes", "BUY", 100, 0.50, 0.0)
        prices = {"1:Yes": 0.60}
        # Cash = 10000 - 50 = 9950, position value = 100 * 0.60 = 60
        assert p.total_value(prices) == pytest.approx(10010.0)

    def test_no_prices_ignores_positions(self):
        p = Portfolio(10000.0)
        p.execute_trade(1, "Yes", "BUY", 100, 0.50, 0.0)
        assert p.total_value() == pytest.approx(9950.0)


class TestUnrealizedPnl:
    def test_no_positions(self):
        p = Portfolio(10000.0)
        assert p.unrealized_pnl({"1:Yes": 0.5}) == 0.0

    def test_long_profit(self):
        p = Portfolio(10000.0)
        p.execute_trade(1, "Yes", "BUY", 100, 0.50, 0.0)
        # Unrealized = 100 * 0.70 - 50.0 = 20.0
        assert p.unrealized_pnl({"1:Yes": 0.70}) == pytest.approx(20.0)

    def test_short_profit(self):
        p = Portfolio(10000.0)
        p.execute_trade(1, "Yes", "SELL", 100, 0.60, 0.0)
        # Short unrealized = credit - close_cost = 60 - 100*0.40 = 20
        assert p.unrealized_pnl({"1:Yes": 0.40}) == pytest.approx(20.0)


class TestPositionsInProfit:
    def test_no_positions(self):
        p = Portfolio(10000.0)
        assert p.positions_in_profit({"1:Yes": 0.5}) == (0, 0)

    def test_one_profitable_one_losing(self):
        p = Portfolio(10000.0)
        p.execute_trade(1, "Yes", "BUY", 100, 0.50, 0.0)
        p.execute_trade(2, "Yes", "BUY", 100, 0.70, 0.0)
        prices = {"1:Yes": 0.80, "2:Yes": 0.50}
        in_profit, total = p.positions_in_profit(prices)
        assert total == 2
        assert in_profit == 1

    def test_short_position_in_profit(self):
        # Open a short: sell 100 shares at $0.60 → credit = 60
        p = Portfolio(10000.0)
        p.execute_trade(1, "Yes", "SELL", 100, 0.60, 0.0)
        # Price drops to 0.40 → cost to close = 40 < credit 60 → in profit
        in_profit, total = p.positions_in_profit({"1:Yes": 0.40})
        assert total == 1
        assert in_profit == 1

    def test_short_position_losing(self):
        # Open a short: sell 100 shares at $0.40 → credit = 40
        p = Portfolio(10000.0)
        p.execute_trade(1, "Yes", "SELL", 100, 0.40, 0.0)
        # Price rises to 0.70 → cost to close = 70 > credit 40 → losing
        in_profit, total = p.positions_in_profit({"1:Yes": 0.70})
        assert total == 1
        assert in_profit == 0


class TestMarkSettled:
    def test_settled_trade_increments_count(self):
        p = Portfolio(10000.0)
        p.mark_settled(is_winner=False)
        assert p.settled_trades == 1
        assert p.winning_trades == 0

    def test_winner_increments_winning_trades(self):
        p = Portfolio(10000.0)
        p.mark_settled(is_winner=True)
        assert p.settled_trades == 1
        assert p.winning_trades == 1

    def test_multiple_settlements(self):
        p = Portfolio(10000.0)
        p.mark_settled(is_winner=True)
        p.mark_settled(is_winner=True)
        p.mark_settled(is_winner=False)
        assert p.settled_trades == 3
        assert p.winning_trades == 2


class TestSnapshotDict:
    def test_snapshot_fields(self):
        p = Portfolio(10000.0)
        snap = p.to_snapshot_dict()
        assert "cash" in snap
        assert "positions" in snap
        assert "total_value" in snap
        assert "realized_pnl" in snap
        assert "unrealized_pnl" in snap
        assert "total_trades" in snap
        assert snap["cash"] == pytest.approx(10000.0)
