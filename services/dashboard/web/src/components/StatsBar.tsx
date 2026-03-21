import React from "react";
import type { Stats } from "../hooks/useDashboardData.ts";

interface Props {
  stats: Stats | null;
  onStatClick?: (tab: string) => void;
}

const StatsBar = React.memo(function StatsBar({ stats, onStatClick }: Props) {
  if (!stats) return <div style={styles.bar}>Loading...</div>;

  const p = stats.portfolio;

  // Unrealized win rate: % of open positions currently in profit
  // (approximated from unrealized PNL > 0 when we have positions)
  const unrealizedWinRate =
    p && p.total_positions > 0 && p.unrealized_pnl > 0
      ? `~${Math.min(100, Math.round((p.unrealized_pnl / p.total_value) * 1000))}%`
      : p && p.total_positions > 0
        ? "0%"
        : "\u2014";

  // Realized win rate: nothing has resolved yet
  const realizedWinRate =
    p && p.winning_trades > 0
      ? `${((p.winning_trades / p.total_trades) * 100).toFixed(1)}%`
      : null;

  return (
    <div style={styles.bar}>
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
      <div style={styles.pnlGroup}>
        <div style={styles.pnlGroupLabel}>PnL</div>
        <div style={styles.pnlRow}>
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
      <div style={styles.pnlItem}>
        <div style={styles.pnlLabel}>{label}</div>
        <div style={styles.pnlAmount}>{"\u2014"}</div>
      </div>
    );
  }

  const color = amount >= 0 ? "#00ff88" : "#ff4444";
  const sign = amount >= 0 ? "+" : "";
  const pct = total && total > 0 ? ` (${sign}${((amount / total) * 100).toFixed(1)}%)` : "";

  return (
    <div style={styles.pnlItem}>
      <div style={styles.pnlLabel}>{label}</div>
      <div
        style={{
          ...styles.pnlAmount,
          color,
          fontWeight: bold ? 700 : 600,
        }}
      >
        {sign}${amount.toFixed(2)}{pct}
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  color,
  onClick,
  small,
}: {
  label: string;
  value: string;
  color?: string;
  onClick?: () => void;
  small?: boolean;
}) {
  return (
    <div
      style={{
        ...styles.stat,
        ...(onClick ? styles.clickable : {}),
      }}
      onClick={onClick}
    >
      <div style={styles.label}>{label}</div>
      <div
        style={{
          ...styles.value,
          color: color || "#e0e0e0",
          ...(small ? { fontSize: 14 } : {}),
        }}
      >
        {value}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  bar: {
    display: "flex",
    gap: 24,
    padding: "16px 20px",
    background: "#111118",
    borderRadius: 8,
    marginBottom: 20,
    flexWrap: "wrap",
    alignItems: "flex-start",
  },
  stat: { minWidth: 80 },
  clickable: { cursor: "pointer" },
  label: {
    fontSize: 11,
    color: "#666",
    textTransform: "uppercase",
    marginBottom: 4,
  },
  value: { fontSize: 20, fontWeight: 600 },
  pnlGroup: {
    minWidth: 200,
  },
  pnlGroupLabel: {
    fontSize: 11,
    color: "#666",
    textTransform: "uppercase",
    marginBottom: 4,
  },
  pnlRow: {
    display: "flex",
    gap: 16,
  },
  pnlItem: {},
  pnlLabel: {
    fontSize: 9,
    color: "#555",
    textTransform: "uppercase",
    marginBottom: 2,
  },
  pnlAmount: {
    fontSize: 16,
    fontWeight: 600,
    fontFamily: "monospace",
  },
};
