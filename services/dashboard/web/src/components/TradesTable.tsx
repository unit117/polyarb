import React, { useMemo } from "react";
import type { Trade, PaginationInfo } from "../hooks/useDashboardData.ts";
import LoadMoreBar from "./LoadMoreBar.tsx";

interface Props {
  trades: Trade[];
  pagination: PaginationInfo;
  onLoadMore: () => void;
  loading: boolean;
}

const TradesTable = React.memo(function TradesTable({ trades, pagination, onLoadMore, loading }: Props) {
  // Group trades by opportunity_id for visual grouping
  const groupedTrades = useMemo(() => {
    const groups: Map<number, Trade[]> = new Map();
    for (const t of trades) {
      const key = t.opportunity_id;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(t);
    }
    return groups;
  }, [trades]);

  let groupIndex = 0;

  return (
    <div style={styles.wrap}>
      <table style={styles.table}>
        <thead>
          <tr>
            <th style={styles.th}>Time</th>
            <th style={styles.th}>Source</th>
            <th style={styles.th}>Market</th>
            <th style={styles.th}>Outcome</th>
            <th style={styles.th}>Side</th>
            <th style={styles.th}>Size</th>
            <th style={styles.th}>Price Paid</th>
            <th style={styles.th}>Avg Fill</th>
            <th style={styles.th}>Price Impact</th>
            <th style={styles.th}>Fees</th>
            <th style={styles.th}>Trade Reason</th>
          </tr>
        </thead>
        <tbody>
          {Array.from(groupedTrades.entries()).map(([oppId, group]) => {
            const isEven = groupIndex % 2 === 0;
            groupIndex++;
            const groupBg = isEven ? "transparent" : "rgba(255,255,255,0.02)";

            return group.map((t, i) => (
              <tr
                key={t.id}
                style={{
                  ...styles.row,
                  background: groupBg,
                  ...(i === 0 && group.length > 1
                    ? { borderTop: "1px solid #2a2a3a" }
                    : {}),
                }}
              >
                <td style={styles.td}>
                  {new Date(t.executed_at).toLocaleTimeString()}
                </td>
                <td style={styles.td}>
                  <span style={{
                    padding: "2px 6px",
                    borderRadius: 3,
                    fontSize: 10,
                    fontWeight: 600,
                    textTransform: "uppercase",
                    background: t.source === "live" ? "#2e1a1a" : "#1a2e1a",
                    color: t.source === "live" ? "#ff6644" : "#00ff88",
                  }}>
                    {t.source || "paper"}
                  </span>
                </td>
                <td style={{ ...styles.td, maxWidth: 220 }}>{t.market}</td>
                <td style={styles.td}>{t.outcome}</td>
                <td style={styles.td}>
                  <span
                    style={{
                      color: t.side === "BUY" ? "#00ff88" : "#ff4444",
                      fontWeight: 600,
                    }}
                  >
                    {t.side}
                  </span>
                </td>
                <td style={styles.tdNum}>{t.size.toFixed(2)}</td>
                <td style={styles.tdNum}>{t.entry_price.toFixed(4)}</td>
                <td style={styles.tdNum}>{t.vwap_price.toFixed(4)}</td>
                <td style={styles.tdNum}>
                  {(t.slippage * 100).toFixed(2)}%
                </td>
                <td style={styles.tdNum}>${t.fees.toFixed(4)}</td>
                <td style={styles.tdReason}>
                  {i === 0 ? formatTradeReason(group) : ""}
                </td>
              </tr>
            ));
          })}
          {trades.length === 0 && (
            <tr>
              <td
                colSpan={11}
                style={{ ...styles.td, textAlign: "center", color: "#555" }}
              >
                No trades yet
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <LoadMoreBar
        pagination={pagination}
        loadedCount={trades.length}
        onLoadMore={onLoadMore}
        loading={loading}
      />
    </div>
  );
});

export default TradesTable;

function formatTradeReason(group: Trade[]): string {
  if (group.length < 2) {
    const t = group[0];
    return `${t.side} ${t.outcome}@${t.entry_price.toFixed(3)}`;
  }
  // Format as arb explanation
  const parts = group.map(
    (t) => `${t.side} ${t.outcome}@${t.entry_price.toFixed(3)}`,
  );
  const totalCost = group.reduce(
    (sum, t) => sum + (t.side === "BUY" ? t.vwap_price * t.size : 0),
    0,
  );
  const totalSize = group.reduce(
    (sum, t) => sum + (t.side === "BUY" ? t.size : 0),
    0,
  );
  const avgCost = totalSize > 0 ? totalCost / totalSize : 0;

  return `Arb: ${parts.join(" + ")}${avgCost > 0 ? `, cost ${avgCost.toFixed(3)}` : ""}`;
}

const styles: Record<string, React.CSSProperties> = {
  wrap: { overflowX: "auto" },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 12 },
  th: {
    textAlign: "left",
    padding: "8px 10px",
    borderBottom: "1px solid #333",
    color: "#666",
    fontSize: 11,
    textTransform: "uppercase",
    whiteSpace: "nowrap",
  },
  row: { borderBottom: "1px solid #1a1a1a" },
  td: {
    padding: "8px 10px",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  tdNum: {
    padding: "8px 10px",
    fontFamily: "monospace",
    textAlign: "right",
  },
  tdReason: {
    padding: "8px 10px",
    fontSize: 10,
    color: "#888",
    maxWidth: 300,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
};
