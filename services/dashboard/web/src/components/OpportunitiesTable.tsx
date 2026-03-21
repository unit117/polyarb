import React, { useMemo, useState } from "react";
import type { Opportunity, PaginationInfo } from "../hooks/useDashboardData.ts";
import LoadMoreBar from "./LoadMoreBar.tsx";

interface Props {
  opportunities: Opportunity[];
  pagination: PaginationInfo;
  onLoadMore: () => void;
  loading: boolean;
}

const OpportunitiesTable = React.memo(function OpportunitiesTable({
  opportunities,
  pagination,
  onLoadMore,
  loading,
}: Props) {
  const [showUnprofitable, setShowUnprofitable] = useState(false);

  const sorted = useMemo(() => {
    const filtered = showUnprofitable
      ? opportunities
      : opportunities.filter((o) => o.estimated_profit > 0);
    return [...filtered].sort(
      (a, b) => b.estimated_profit - a.estimated_profit,
    );
  }, [opportunities, showUnprofitable]);

  const hiddenCount = opportunities.length - sorted.length;

  return (
    <div style={styles.wrap}>
      {!showUnprofitable && hiddenCount > 0 && (
        <div style={styles.filterBar}>
          <span style={{ color: "#888", fontSize: 12 }}>
            Showing {sorted.length} profitable opportunities.{" "}
          </span>
          <button
            style={styles.toggleBtn}
            onClick={() => setShowUnprofitable(true)}
          >
            Show all {opportunities.length} ({hiddenCount} with zero profit
            after fees)
          </button>
        </div>
      )}
      {showUnprofitable && (
        <div style={styles.filterBar}>
          <span style={{ color: "#888", fontSize: 12 }}>
            Showing all {sorted.length} opportunities.{" "}
          </span>
          <button
            style={styles.toggleBtn}
            onClick={() => setShowUnprofitable(false)}
          >
            Hide zero-profit
          </button>
        </div>
      )}
      <table style={styles.table}>
        <thead>
          <tr>
            <th style={styles.th}>Time</th>
            <th style={styles.th}>Status</th>
            <th style={styles.th}>Type</th>
            <th style={styles.th}>Market A</th>
            <th style={styles.th}>Market B</th>
            <th style={styles.th}>Dep.</th>
            <th style={styles.th}>Theo. Profit</th>
            <th style={styles.th}>
              Est. Profit
              <span
                style={{ fontSize: 9, color: "#555", display: "block" }}
              >
                after fees
              </span>
            </th>
            <th style={styles.th} title="Frank-Wolfe optimizer iterations to convergence">
              Optimizer Iters
            </th>
            <th style={styles.th} title="Bregman divergence gap — lower = better convergence">
              Gap
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((o) => {
            const profitColor =
              o.estimated_profit > 0.01
                ? "#00ff88"
                : o.estimated_profit > 0
                  ? "#ffcc00"
                  : "#555";

            return (
              <tr
                key={o.id}
                style={{
                  ...styles.row,
                  background:
                    o.estimated_profit > 0.01
                      ? "rgba(0,255,136,0.03)"
                      : o.estimated_profit > 0
                        ? "rgba(255,204,0,0.03)"
                        : "transparent",
                }}
              >
                <td style={styles.td}>
                  {o.timestamp
                    ? new Date(o.timestamp).toLocaleTimeString()
                    : "\u2014"}
                </td>
                <td style={styles.td}>
                  <span
                    style={{ ...styles.badge, ...statusColor(o.status) }}
                  >
                    {o.status}
                  </span>
                </td>
                <td style={styles.td}>{o.type}</td>
                <td style={{ ...styles.td, maxWidth: 200 }}>
                  {o.pair?.market_a || "\u2014"}
                </td>
                <td style={{ ...styles.td, maxWidth: 200 }}>
                  {o.pair?.market_b || "\u2014"}
                </td>
                <td style={styles.td}>
                  {o.pair?.dependency_type || "\u2014"}
                </td>
                <td style={styles.tdNum}>
                  {o.theoretical_profit.toFixed(4)}
                </td>
                <td style={{ ...styles.tdNum, color: profitColor }}>
                  {o.estimated_profit.toFixed(4)}
                </td>
                <td style={styles.tdNum}>
                  {o.fw_iterations ?? "\u2014"}
                </td>
                <td style={styles.tdNum}>
                  {o.bregman_gap != null
                    ? o.bregman_gap.toFixed(6)
                    : "\u2014"}
                </td>
              </tr>
            );
          })}
          {sorted.length === 0 && (
            <tr>
              <td
                colSpan={10}
                style={{ ...styles.td, textAlign: "center", color: "#555" }}
              >
                {opportunities.length === 0
                  ? "No opportunities yet"
                  : "No profitable opportunities (toggle to see all)"}
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <LoadMoreBar
        pagination={pagination}
        loadedCount={opportunities.length}
        onLoadMore={onLoadMore}
        loading={loading}
      />
    </div>
  );
});

export default OpportunitiesTable;

function statusColor(s: string): React.CSSProperties {
  switch (s) {
    case "detected":
      return { background: "#2a2a00", color: "#ffcc00" };
    case "optimized":
      return { background: "#002a00", color: "#00ff88" };
    case "simulated":
      return { background: "#00002a", color: "#4488ff" };
    case "unconverged":
      return { background: "#2a0000", color: "#ff6644" };
    default:
      return { background: "#1a1a1a", color: "#888" };
  }
}

const styles: Record<string, React.CSSProperties> = {
  wrap: { overflowX: "auto" },
  filterBar: {
    padding: "8px 10px",
    marginBottom: 8,
  },
  toggleBtn: {
    background: "transparent",
    border: "1px solid #333",
    borderRadius: 4,
    color: "#4488ff",
    cursor: "pointer",
    fontSize: 12,
    padding: "2px 8px",
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    fontSize: 12,
  },
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
  badge: {
    padding: "2px 8px",
    borderRadius: 4,
    fontSize: 11,
    fontWeight: 600,
  },
};
