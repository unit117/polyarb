import React, { useMemo, useState } from "react";
import type { Opportunity, PaginationInfo } from "../hooks/useDashboardData.ts";
import LoadMoreBar from "./LoadMoreBar.tsx";
import s from "./OpportunitiesTable.module.css";

interface Props {
  opportunities: Opportunity[];
  pagination: PaginationInfo;
  onLoadMore: () => void;
  loading: boolean;
  onSelect?: (opp: Opportunity) => void;
}

const OpportunitiesTable = React.memo(function OpportunitiesTable({
  opportunities,
  pagination,
  onLoadMore,
  loading,
  onSelect,
}: Props) {
  const [showUnprofitable, setShowUnprofitable] = useState(false);

  // Sort only the initial page; after "Load More" appends, preserve order
  // so newly loaded items don't jump around mid-scroll.
  const sorted = useMemo(() => {
    const filtered = showUnprofitable
      ? opportunities
      : opportunities.filter((o) => o.estimated_profit > 0 && o.status !== "expired");
    if (pagination.offset === 0) {
      return [...filtered].sort(
        (a, b) => b.estimated_profit - a.estimated_profit,
      );
    }
    return filtered;
  }, [opportunities, showUnprofitable, pagination.offset]);

  const hiddenCount = opportunities.length - sorted.length;

  const filterBar = (
    <>
      {!showUnprofitable && hiddenCount > 0 && (
        <div className={s.filterBar}>
          <span className={s.filterText}>
            Showing {sorted.length} profitable.{" "}
          </span>
          <button className={s.toggleBtn} onClick={() => setShowUnprofitable(true)}>
            Show all {opportunities.length}
          </button>
        </div>
      )}
      {showUnprofitable && (
        <div className={s.filterBar}>
          <span className={s.filterText}>
            Showing all {sorted.length}.{" "}
          </span>
          <button className={s.toggleBtn} onClick={() => setShowUnprofitable(false)}>
            Hide zero-profit
          </button>
        </div>
      )}
    </>
  );

  return (
    <div className={s.wrap}>
      {filterBar}

      {/* Desktop table */}
      <table className={s.table}>
        <thead>
          <tr>
            <th className={s.th}>Time</th>
            <th className={s.th}>Status</th>
            <th className={s.th}>Type</th>
            <th className={s.th}>Market A</th>
            <th className={s.th}>Market B</th>
            <th className={s.th}>Dep.</th>
            <th className={s.th}>Theo. Profit</th>
            <th className={s.th}>
              Est. Profit
              <span className={s.thSub}>after fees</span>
            </th>
            <th className={s.th} title="Frank-Wolfe optimizer iterations to convergence">
              Optimizer Iters
            </th>
            <th className={s.th} title="Bregman divergence gap — lower = better convergence">
              Gap
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((o) => {
            const profitClass =
              o.estimated_profit > 0.01
                ? s.profitGreen
                : o.estimated_profit > 0
                  ? s.profitYellow
                  : s.profitGray;

            const rowClass = [
              s.row,
              o.estimated_profit > 0.01 ? s.rowProfitable : "",
              o.estimated_profit > 0 && o.estimated_profit <= 0.01 ? s.rowMarginal : "",
            ].filter(Boolean).join(" ");

            return (
              <tr
                key={o.id}
                className={rowClass}
                onClick={() => onSelect?.(o)}
              >
                <td className={s.td}>
                  {o.timestamp
                    ? new Date(o.timestamp).toLocaleTimeString()
                    : "\u2014"}
                </td>
                <td className={s.td}>
                  <span className={`${s.badge} ${statusClass(o.status)}`}>
                    {o.status}
                  </span>
                </td>
                <td className={s.td}>{o.type}</td>
                <td className={s.tdMarket}>
                  {o.pair?.market_a_venue && o.pair.market_a_venue !== "polymarket" && (
                    <span className={`${s.venueBadge} ${s.venueKalshi}`}>{o.pair.market_a_venue}</span>
                  )}
                  {o.pair?.market_a || "\u2014"}
                </td>
                <td className={s.tdMarket}>
                  {o.pair?.market_b_venue && o.pair.market_b_venue !== "polymarket" && (
                    <span className={`${s.venueBadge} ${s.venueKalshi}`}>{o.pair.market_b_venue}</span>
                  )}
                  {o.pair?.market_b || "\u2014"}
                </td>
                <td className={s.td}>
                  {o.pair?.dependency_type || "\u2014"}
                </td>
                <td className={s.tdNum}>
                  {o.theoretical_profit.toFixed(4)}
                </td>
                <td className={`${s.tdNum} ${profitClass}`}>
                  {o.estimated_profit.toFixed(4)}
                </td>
                <td className={s.tdNum}>
                  {o.fw_iterations ?? "\u2014"}
                </td>
                <td className={s.tdNum}>
                  {o.bregman_gap != null
                    ? o.bregman_gap.toFixed(6)
                    : "\u2014"}
                </td>
              </tr>
            );
          })}
          {sorted.length === 0 && (
            <tr>
              <td colSpan={10} className={s.empty}>
                {opportunities.length === 0
                  ? "No opportunities yet"
                  : "No profitable opportunities (toggle to see all)"}
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {/* Mobile card list */}
      <div className={s.cardList}>
        {sorted.map((o) => {
          const profitClass =
            o.estimated_profit > 0.01
              ? s.profitGreen
              : o.estimated_profit > 0
                ? s.profitYellow
                : s.profitGray;
          return (
            <div key={o.id} className={s.card} onClick={() => onSelect?.(o)}>
              <div className={s.cardHeader}>
                <span className={`${s.badge} ${statusClass(o.status)}`}>{o.status}</span>
                <span className={s.cardTime}>
                  {o.timestamp ? new Date(o.timestamp).toLocaleTimeString() : "\u2014"}
                </span>
              </div>
              <div className={s.cardMarket}>{o.pair?.market_a || "\u2014"}</div>
              <div className={s.cardMarket}>{o.pair?.market_b || "\u2014"}</div>
              <div className={s.cardRow}>
                <span className={s.cardLabel}>Est. Profit</span>
                <span className={profitClass}>{o.estimated_profit.toFixed(4)}</span>
              </div>
              <div className={s.cardRow}>
                <span className={s.cardLabel}>Type</span>
                <span>{o.pair?.dependency_type || o.type}</span>
              </div>
            </div>
          );
        })}
        {sorted.length === 0 && (
          <div className={s.empty}>
            {opportunities.length === 0
              ? "No opportunities yet"
              : "No profitable opportunities (toggle to see all)"}
          </div>
        )}
      </div>

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

function statusClass(status: string): string {
  switch (status) {
    case "detected":    return s.statusDetected;
    case "optimized":   return s.statusOptimized;
    case "simulated":   return s.statusSimulated;
    case "unconverged": return s.statusUnconverged;
    case "expired":     return s.statusExpired;
    case "skipped":     return s.statusSkipped;
    default:            return s.statusDefault;
  }
}
