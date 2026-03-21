import React from "react";
import type { Stats } from "../hooks/useDashboardData.ts";
import s from "./StatsBar.module.css";

interface Props {
  stats: Stats | null;
  onStatClick?: (tab: string) => void;
}

const StatsBar = React.memo(function StatsBar({ stats, onStatClick }: Props) {
  if (!stats) return <div className={s.bar}>Loading...</div>;

  const p = stats.portfolio;

  const unrealizedWinRate =
    p && p.total_positions > 0 && p.unrealized_pnl > 0
      ? `~${Math.min(100, Math.round((p.unrealized_pnl / p.total_value) * 1000))}%`
      : p && p.total_positions > 0
        ? "0%"
        : "\u2014";

  const realizedWinRate =
    p && p.settled_trades > 0
      ? `${((p.winning_trades / p.settled_trades) * 100).toFixed(1)}%`
      : null;

  return (
    <div className={s.bar}>
      <Stat
        label="Markets"
        value={stats.active_markets.toLocaleString()}
      />
      <Stat
        label="Pairs"
        value={stats.market_pairs.toLocaleString()}
        onClick={() => onStatClick?.("pairs")}
      />
      <Stat
        label="Opportunities"
        value={stats.total_opportunities.toLocaleString()}
        onClick={() => onStatClick?.("opportunities")}
      />
      <Stat
        label="Trades"
        value={stats.total_trades.toLocaleString()}
        onClick={() => onStatClick?.("trades")}
      />
      <Stat
        label="Portfolio"
        value={p ? `$${p.total_value.toFixed(2)}` : "\u2014"}
      />
      <div className={s.pnlGroup}>
        <div className={s.pnlGroupLabel}>PnL</div>
        <div className={s.pnlRow}>
          <PnlValue label="Unrealized" amount={p?.unrealized_pnl ?? null} total={p?.total_value ?? null} />
          <PnlValue label="Realized" amount={p?.realized_pnl ?? null} total={p?.total_value ?? null} />
          <PnlValue label="Total" amount={p?.total_pnl ?? null} total={p?.total_value ?? null} bold />
        </div>
      </div>
      <Stat
        label="Win Rate"
        value={
          realizedWinRate
            ? realizedWinRate
            : p && p.total_positions > 0
              ? `${unrealizedWinRate} unrealized`
              : "No positions yet"
        }
        small
      />
    </div>
  );
});

export default StatsBar;

function PnlValue({
  label,
  amount,
  total,
  bold,
}: {
  label: string;
  amount: number | null;
  total: number | null;
  bold?: boolean;
}) {
  if (amount === null) {
    return (
      <div className={s.pnlItem}>
        <div className={s.pnlLabel}>{label}</div>
        <div className={s.pnlAmount}>{"\u2014"}</div>
      </div>
    );
  }

  const isPositive = amount >= 0;
  const sign = isPositive ? "+" : "";
  const pct = total && total > 0 ? ` (${sign}${((amount / total) * 100).toFixed(1)}%)` : "";
  const trendClass = isPositive ? s.trendUp : s.trendDown;

  return (
    <div className={s.pnlItem}>
      <div className={s.pnlLabel}>{label}</div>
      <div className={`${s.pnlAmount} ${isPositive ? s.positive : s.negative} ${bold ? s.pnlBold : ""}`}>
        {sign}${amount.toFixed(2)}{pct}
        <span className={trendClass}>{isPositive ? "\u25B2" : "\u25BC"}</span>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  onClick,
  small,
}: {
  label: string;
  value: string;
  onClick?: () => void;
  small?: boolean;
}) {
  return (
    <div
      className={`${s.stat} ${onClick ? s.clickable : ""}`}
      onClick={onClick}
    >
      <div className={s.label}>{label}</div>
      <div className={`${s.value} ${small ? s.valueSmall : ""}`}>
        {value}
      </div>
    </div>
  );
}
