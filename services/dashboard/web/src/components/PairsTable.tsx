import React, { useMemo, useState } from "react";
import type { Pair, PaginationInfo } from "../hooks/useDashboardData.ts";
import LoadMoreBar from "./LoadMoreBar.tsx";
import s from "./PairsTable.module.css";

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

  // Sort only the initial page; after "Load More" appends, preserve order
  const sorted = useMemo(() => {
    const filtered = showEmpty
      ? pairs
      : pairs.filter((p) => p.opportunity_count > 0);
    if (pagination.offset === 0) {
      return [...filtered].sort((a, b) => b.confidence - a.confidence);
    }
    return filtered;
  }, [pairs, showEmpty, pagination.offset]);

  const hiddenCount = pairs.length - sorted.length;

  return (
    <div className={s.wrap}>
      <div className={s.explainer}>
        Pairs are markets whose outcomes are logically linked. The bot
        monitors their prices for inconsistencies.
      </div>

      {!showEmpty && hiddenCount > 0 && (
        <div className={s.filterBar}>
          <span className={s.filterText}>
            Showing {sorted.length} pairs with opportunities.{" "}
          </span>
          <button
            className={s.toggleBtn}
            onClick={() => setShowEmpty(true)}
          >
            Show all {pairs.length} ({hiddenCount} with 0 opportunities)
          </button>
        </div>
      )}
      {showEmpty && (
        <div className={s.filterBar}>
          <span className={s.filterText}>
            Showing all {sorted.length} pairs.{" "}
          </span>
          <button
            className={s.toggleBtn}
            onClick={() => setShowEmpty(false)}
          >
            Hide pairs with 0 opportunities
          </button>
        </div>
      )}

      {/* Desktop table */}
      <table className={s.table}>
        <thead>
          <tr>
            <th className={s.th}>Detected</th>
            <th className={s.th}>Market A</th>
            <th className={s.th}>Market B</th>
            <th className={s.th}>Relationship</th>
            <th className={s.th}>Confidence</th>
            <th className={s.th}>Opportunities</th>
            <th className={s.th}>Verified</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((p) => (
            <tr key={p.id} className={s.row}>
              <td className={s.td}>
                {p.detected_at
                  ? new Date(p.detected_at).toLocaleDateString()
                  : "\u2014"}
              </td>
              <td className={s.tdMarket}>
                {p.market_a?.venue && p.market_a.venue !== "polymarket" && (
                  <span className={s.venueBadge}>{p.market_a.venue}</span>
                )}
                {p.market_a?.question || "\u2014"}
              </td>
              <td className={s.tdMarket}>
                {p.market_b?.venue && p.market_b.venue !== "polymarket" && (
                  <span className={s.venueBadge}>{p.market_b.venue}</span>
                )}
                {p.market_b?.question || "\u2014"}
              </td>
              <td className={s.td}>
                <span
                  className={s.depBadge}
                  title={
                    DEP_LABELS[p.dependency_type] || p.dependency_type
                  }
                >
                  {formatDepType(p.dependency_type)}
                </span>
              </td>
              <td className={s.confidenceCell}>
                <ConfidenceMeter value={p.confidence} />
              </td>
              <td className={s.tdNum}>{p.opportunity_count}</td>
              <td className={s.td}>
                {p.verified ? (
                  <span className={s.verifiedYes}>Yes</span>
                ) : (
                  <span className={s.verifiedNo}>No</span>
                )}
              </td>
            </tr>
          ))}
          {sorted.length === 0 && (
            <tr>
              <td colSpan={7} className={s.empty}>
                {pairs.length === 0
                  ? "No pairs detected yet"
                  : "No pairs with opportunities (toggle to see all)"}
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {/* Mobile card list */}
      <div className={s.cardList}>
        {sorted.map((p) => (
          <div key={p.id} className={s.card}>
            <div className={s.cardHeader}>
              <span className={s.depBadge}>{formatDepType(p.dependency_type)}</span>
              <ConfidenceMeter value={p.confidence} />
            </div>
            <div className={s.cardMarket}>{p.market_a?.question || "\u2014"}</div>
            <div className={s.cardMarket}>{p.market_b?.question || "\u2014"}</div>
            <div className={s.cardRow}>
              <span className={s.cardLabel}>Opps</span>
              <span>{p.opportunity_count}</span>
            </div>
          </div>
        ))}
        {sorted.length === 0 && (
          <div className={s.empty}>
            {pairs.length === 0
              ? "No pairs detected yet"
              : "No pairs with opportunities (toggle to see all)"}
          </div>
        )}
      </div>
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

function ConfidenceMeter({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const fillClass =
    pct >= 80 ? s.confidenceHigh :
    pct >= 50 ? s.confidenceMedium :
    s.confidenceLow;

  return (
    <div className={s.confidenceBar}>
      <div className={s.confidenceTrack}>
        <div
          className={`${s.confidenceFill} ${fillClass}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={s.confidenceValue}>{pct}%</span>
    </div>
  );
}

function formatDepType(dt: string): string {
  return dt
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
