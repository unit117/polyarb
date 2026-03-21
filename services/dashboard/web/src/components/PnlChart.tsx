import React, { useMemo } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import type { HistoryPoint } from "../hooks/useDashboardData.ts";

interface Props {
  history: HistoryPoint[];
  initialCapital?: number;
}

const INITIAL_CAPITAL = 10000;

const PnlChart = React.memo(function PnlChart({
  history,
  initialCapital = INITIAL_CAPITAL,
}: Props) {
  const chartData = useMemo(
    () =>
      history.map((d) => ({
        time: new Date(d.timestamp).toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        }),
        value: d.total_value,
        pnl: d.unrealized_pnl ?? d.total_value - initialCapital,
      })),
    [history, initialCapital],
  );

  const [yMin, yMax] = useMemo(() => {
    if (chartData.length === 0) return [0, 0];
    const values = chartData.map((d) => d.value);
    const min = Math.min(...values, initialCapital);
    const max = Math.max(...values, initialCapital);
    const range = max - min || 100;
    const padding = range * 0.15;
    return [
      Math.floor((min - padding) / 10) * 10,
      Math.ceil((max + padding) / 10) * 10,
    ];
  }, [chartData, initialCapital]);

  if (chartData.length === 0) {
    return (
      <div style={styles.empty}>
        No portfolio data yet. Waiting for first trades...
      </div>
    );
  }

  return (
    <div style={styles.container}>
      <h3 style={styles.title}>Portfolio Value (24h)</h3>
      <ResponsiveContainer width="100%" height={250}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#222" />
          <XAxis
            dataKey="time"
            stroke="#555"
            fontSize={11}
            interval={Math.max(0, Math.floor(chartData.length / 8) - 1)}
            angle={0}
          />
          <YAxis
            stroke="#555"
            fontSize={11}
            domain={[yMin, yMax]}
            tickFormatter={(v: number) => `$${v.toLocaleString()}`}
          />
          <Tooltip content={<CustomTooltip initialCapital={initialCapital} />} />
          <ReferenceLine
            y={initialCapital}
            stroke="#666"
            strokeDasharray="6 3"
            label={{
              value: `Starting $${initialCapital.toLocaleString()}`,
              position: "insideTopRight",
              fill: "#666",
              fontSize: 10,
            }}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke="#00ff88"
            strokeWidth={2}
            dot={false}
            name="Portfolio Value"
          />
          <Line
            type="monotone"
            dataKey="pnl"
            stroke="#4488ff"
            strokeWidth={1.5}
            dot={false}
            strokeDasharray="4 2"
            name="Unrealized PnL"
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
});

export default PnlChart;

function CustomTooltip({
  active,
  payload,
  initialCapital,
}: {
  active?: boolean;
  payload?: Array<{ value: number; name: string; color: string }>;
  label?: string;
  initialCapital: number;
}) {
  if (!active || !payload || payload.length === 0) return null;

  const value = payload[0]?.value ?? 0;
  const pnl = value - initialCapital;
  const pnlColor = pnl >= 0 ? "#00ff88" : "#ff4444";
  const sign = pnl >= 0 ? "+" : "";

  return (
    <div style={tooltipStyles.container}>
      <div style={tooltipStyles.row}>
        <span style={{ color: "#888" }}>Value:</span>
        <span style={{ color: "#e0e0e0", fontWeight: 600 }}>
          ${value.toFixed(2)}
        </span>
      </div>
      <div style={tooltipStyles.row}>
        <span style={{ color: "#888" }}>PnL:</span>
        <span style={{ color: pnlColor, fontWeight: 600 }}>
          {sign}${pnl.toFixed(2)} ({sign}
          {((pnl / initialCapital) * 100).toFixed(2)}%)
        </span>
      </div>
    </div>
  );
}

const tooltipStyles: Record<string, React.CSSProperties> = {
  container: {
    background: "#1a1a2e",
    border: "1px solid #333",
    borderRadius: 6,
    padding: "8px 12px",
    fontSize: 12,
  },
  row: {
    display: "flex",
    justifyContent: "space-between",
    gap: 16,
    lineHeight: 1.6,
  },
};

const styles: Record<string, React.CSSProperties> = {
  container: {
    background: "#111118",
    borderRadius: 8,
    padding: 20,
    marginBottom: 20,
  },
  title: { margin: "0 0 12px", fontSize: 14, color: "#888" },
  empty: {
    background: "#111118",
    borderRadius: 8,
    padding: 40,
    textAlign: "center",
    color: "#555",
    marginBottom: 20,
    fontSize: 13,
  },
};
