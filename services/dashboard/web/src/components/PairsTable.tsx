import React, { useMemo, useState } from "react";
import type { Pair, PaginationInfo } from "../hooks/useDashboardData.ts";
import LoadMoreBar from "./LoadMoreBar.tsx";

interface Props {
  pairs: Pair[];
  pagination: PaginationInfo;
  onLoadMore: () => void;
  loading: boolean;
}

const DEP_LABELS: Record<string, string> = {
  mutual_exclusion: "Only one can be true (e.g., Team A wins OR Team B wins)",
  conditional:
    "One outcome affects the other (e.g., O/U 6.5 and O/U 7.5)",
  implication: "If A is true, then B must be true",
  partition: "Outcomes together cover all possibilities",
};

const PairsTable = React.memo(function PairsTable({ pairs, pagination, onLoadMore, loading }: Props) {
  const [showEmpty, setShowEmpty] = useState(false);

  const sorted = useMemo(() => {
    const filtered = showEmpty
      ? pairs
      : pairs.filter((p) => p.opportunity_count > 0);
    return [...filtered].sort((a, b) => b.confidence - a.confidence);
  }, [pairs, showEmpty]);

  const hiddenCount = pairs.length - sorted.length;

  return (
    <div style={styles.wrap}>
      <div style={styles.explainer}>
        Pairs are markets whose outcomes are logically linked. The bot
        monitors their prices for inconsistencies.
      </div>

      {!showEmpty && hiddenCount > 0 && (
        <div style={styles.filterBar}>
          <span style={{ color: "#888", fontSize: 12 }}>
            Showing {sorted.length} pairs with opportunities.{" "}
          </span>
          <button
            style={styles.toggleBtn}
            onClick={() => setShowEmpty(true)}
          >
            Show all {pairs.length} ({hiddenCount} with 0 opportunities)
          </button>
        </div>
      )}
      {showEmpty && (
        <div style={styles.filterBar}>
          <span style={{ color: "#888", fontSize: 12 }}>
            Showing all {sorted.length} pairs.{" "}
          </span>
          <button
            style={styles.toggleBtn}
            onClick={() => setShowEmpty(false)}
          >
            Hide pairs with 0 opportunities
          </button>
        </div>
      )}

      <table style={styles.table}>
        <thead>
          <tr>
            <th style={styles.th}>Detected</th>
            <th style={styles.th}>Market A</th>
            <th style={styles.th}>Market B</th>
            <th style={styles.th}>Relationship</th>
            <th style={styles.th}>Confidence</th>
            <th style={styles.th}>Opportunities</th>
            <th style={styles.th}>Verified</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((p) => (
            <tr key={p.id} style={styles.row}>
              <td style={styles.td}>
                {p.detected_at
                  ? new Date(p.detected_at).toLocaleDateString()
                  : "\u2014"}
              </td>
              <td style={{ ...styles.td, maxWidth: 250 }}>
                {p.market_a?.question || "\u2014"}
              </td>
              <td style={{ ...styles.td, maxWidth: 250 }}>
                {p.market_b?.question || "\u2014"}
              </td>
              <td style={styles.td}>
                <span
                  style={styles.depBadge}
                  title={
                    DEP_LABELS[p.dependency_type] || p.dependency_type
                  }
                >
                  {formatDepType(p.dependency_type)}
                </span>
              </td>
              <td style={styles.tdNum}>
                {(p.confidence * 100).toFixed(0)}%
              </td>
              <td style={styles.tdNum}>{p.opportunity_count}</td>
              <td style={styles.td}>
                {p.verified ? (
                  <span style={{ color: "#00ff88" }}>Yes</span>
                ) : (
                  <span style={{ color: "#666" }}>No</span>
                )}
              </td>
            </tr>
          ))}
          {sorted.length === 0 && (
            <tr>
              <td
                colSpan={7}
                style={{
                  ...styles.td,
                  textAlign: "center",
                  color: "#555",
                }}
              >
                {pairs.length === 0
                  ? "No pairs detected yet"
                  : "No pairs with opportunities (toggle to see all)"}
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <LoadMoreBar
        pagination={pagination}
        loadedCount={pairs.length}
        onLoadMore={onLoadMore}
        loading={loading}
      />
    </div>
  );
});

export default PairsTable;

function formatDepType(dt: string): string {
  return dt
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

const styles: Record<string, React.CSSProperties> = {
  wrap: { overflowX: "auto" },
  explainer: {
    fontSize: 12,
    color: "#888",
    padding: "8px 10px",
    marginBottom: 8,
    borderLeft: "2px solid #333",
  },
  filterBar: {
    padding: "4px 10px",
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
  depBadge: {
    padding: "2px 8px",
    borderRadius: 4,
    fontSize: 11,
    background: "#1a1a2e",
    color: "#8888ff",
    cursor: "help",
  },
};
