import React, { useMemo } from "react";
import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import type { HistoryPoint } from "../hooks/useDashboardData.ts";
import s from "./PnlChart.module.css";

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
        cash: d.cash,
        realized: d.realized_pnl,
        unrealized: d.unrealized_pnl,
      })),
    [history],
  );

  const [yMin, yMax] = useMemo(() => {
    if (chartData.length === 0) return [0, 0];
    const allValues = chartData.flatMap((d) => [d.value, d.cash, d.realized, d.unrealized]);
    const min = Math.min(...allValues, initialCapital);
    const max = Math.max(...allValues, initialCapital);
    const range = max - min || 100;
    const padding = range * 0.15;
    return [
      Math.floor((min - padding) / 10) * 10,
      Math.ceil((max + padding) / 10) * 10,
    ];
  }, [chartData, initialCapital]);

  if (chartData.length === 0) {
    return (
      <div className={s.empty}>
        No portfolio data yet. Waiting for first trades...
      </div>
    );
  }

  return (
    <div className={s.container}>
      <h3 className={s.title}>Portfolio Value (24h)</h3>
      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart data={chartData}>
          <defs>
            <linearGradient id="gradientGreen" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#00e67a" stopOpacity={0.2} />
              <stop offset="100%" stopColor="#00e67a" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="gradientBlue" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#4488ff" stopOpacity={0.08} />
              <stop offset="100%" stopColor="#4488ff" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#1a1a2e" />
          <XAxis
            dataKey="time"
            stroke="#555"
            fontSize={11}
            fontFamily="var(--font-mono)"
            interval={Math.max(0, Math.floor(chartData.length / 8) - 1)}
            angle={0}
          />
          <YAxis
            stroke="#555"
            fontSize={11}
            fontFamily="var(--font-mono)"
            domain={[yMin, yMax]}
            tickFormatter={(v: number) => `$${v.toLocaleString()}`}
          />
          <Tooltip content={<CustomTooltip initialCapital={initialCapital} />} />
          <ReferenceLine
            y={initialCapital}
            stroke="#444"
            strokeDasharray="6 3"
            label={{
              value: `Starting $${initialCapital.toLocaleString()}`,
              position: "insideTopRight",
              fill: "#555",
              fontSize: 10,
            }}
          />
          {/* Portfolio Value — primary green area */}
          <Area
            type="monotone"
            dataKey="value"
            stroke="#00e67a"
            strokeWidth={2}
            fill="url(#gradientGreen)"
            dot={false}
            name="Portfolio Value"
          />
          {/* Unrealized PnL — subtle blue area */}
          <Area
            type="monotone"
            dataKey="unrealized"
            stroke="#4488ff"
            strokeWidth={1}
            fill="url(#gradientBlue)"
            dot={false}
            name="Unrealized PnL"
          />
          {/* Cash — gray dashed line */}
          <Line
            type="monotone"
            dataKey="cash"
            stroke="#6b7280"
            strokeWidth={1.5}
            strokeDasharray="4 3"
            dot={false}
            name="Cash"
          />
          {/* Realized PnL — cyan step line */}
          <Line
            type="stepAfter"
            dataKey="realized"
            stroke="#06b6d4"
            strokeWidth={1.5}
            dot={false}
            name="Realized PnL"
          />
        </ComposedChart>
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
  payload?: Array<{ value: number; name: string; color: string; dataKey: string }>;
  label?: string;
  initialCapital: number;
}) {
  if (!active || !payload || payload.length === 0) return null;

  const get = (key: string) => payload.find((p) => p.dataKey === key)?.value ?? 0;
  const value = get("value");
  const cash = get("cash");
  const realized = get("realized");
  const unrealized = get("unrealized");
  const totalPnl = value - initialCapital;
  const pnlPct = ((totalPnl / initialCapital) * 100).toFixed(2);
  const sign = totalPnl >= 0 ? "+" : "";

  return (
    <div className={s.tooltip}>
      <div className={s.tooltipRow}>
        <span className={s.tooltipLabel}>Value:</span>
        <span className={s.tooltipValue}>${value.toFixed(2)}</span>
      </div>
      <div className={s.tooltipRow}>
        <span className={s.tooltipLabel}>Cash:</span>
        <span className={s.tooltipValue}>${cash.toFixed(2)}</span>
      </div>
      <div className={s.tooltipRow}>
        <span className={s.tooltipLabel}>Realized:</span>
        <span className={realized >= 0 ? s.tooltipValuePositive : s.tooltipValueNegative}>
          {realized >= 0 ? "+" : ""}${realized.toFixed(2)}
        </span>
      </div>
      <div className={s.tooltipRow}>
        <span className={s.tooltipLabel}>Unrealized:</span>
        <span className={unrealized >= 0 ? s.tooltipValuePositive : s.tooltipValueNegative}>
          {unrealized >= 0 ? "+" : ""}${unrealized.toFixed(2)}
        </span>
      </div>
      <div className={`${s.tooltipRow} ${s.tooltipTotal}`}>
        <span className={s.tooltipLabel}>Total PnL:</span>
        <span className={totalPnl >= 0 ? s.tooltipValuePositive : s.tooltipValueNegative}>
          {sign}${totalPnl.toFixed(2)} ({sign}{pnlPct}%)
        </span>
      </div>
    </div>
  );
}
