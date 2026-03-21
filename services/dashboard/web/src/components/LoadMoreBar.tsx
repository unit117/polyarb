import React from "react";
import type { PaginationInfo } from "../hooks/useDashboardData.ts";
import s from "./LoadMoreBar.module.css";

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
    <div className={s.bar}>
      <span className={s.info}>
        Showing {loadedCount} of {pagination.total}
      </span>
      {pagination.hasMore && (
        <button
          className={s.btn}
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
