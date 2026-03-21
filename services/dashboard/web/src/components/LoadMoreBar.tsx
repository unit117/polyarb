import React from "react";
import type { PaginationInfo } from "../hooks/useDashboardData.ts";

interface Props {
  pagination: PaginationInfo;
  loadedCount: number;
  onLoadMore: () => void;
  loading: boolean;
}

const LoadMoreBar = React.memo(function LoadMoreBar({
  pagination,
  loadedCount,
  onLoadMore,
  loading,
}: Props) {
  if (pagination.total === 0) return null;

  return (
    <div style={styles.bar}>
      <span style={styles.info}>
        Showing {loadedCount} of {pagination.total}
      </span>
      {pagination.hasMore && (
        <button
          style={styles.btn}
          onClick={onLoadMore}
          disabled={loading}
        >
          {loading ? "Loading..." : `Load more (${pagination.total - loadedCount} remaining)`}
        </button>
      )}
    </div>
  );
});

export default LoadMoreBar;

const styles: Record<string, React.CSSProperties> = {
  bar: {
    padding: "10px 10px",
    display: "flex",
    alignItems: "center",
    gap: 12,
    borderTop: "1px solid #222",
  },
  info: {
    color: "#888",
    fontSize: 12,
  },
  btn: {
    background: "#1a1a2e",
    border: "1px solid #333",
    borderRadius: 4,
    color: "#4488ff",
    cursor: "pointer",
    fontSize: 12,
    padding: "4px 12px",
  },
};
