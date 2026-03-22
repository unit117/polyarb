import React, { useMemo } from "react";
import type { Trade, PaginationInfo } from "../hooks/useDashboardData.ts";
import LoadMoreBar from "./LoadMoreBar.tsx";
import s from "./TradesTable.module.css";

interface Props {
  trades: Trade[];
  pagination: PaginationInfo;
  onLoadMore: () => void;
  loading: boolean;
}

const TradesTable = React.memo(function TradesTable({ trades, pagination, onLoadMore, loading }: Props) {
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
    <div className={s.wrap}>
      {/* Desktop table */}
      <table className={s.table}>
        <thead>
          <tr>
            <th className={s.th}>Time</th>
            <th className={s.th}>Source</th>
            <th className={s.th}>Market</th>
            <th className={s.th}>Outcome</th>
            <th className={s.th}>Side</th>
            <th className={s.th}>Size</th>
            <th className={s.th}>Price Paid</th>
            <th className={s.th}>Avg Fill</th>
            <th className={s.th}>Price Impact</th>
            <th className={s.th}>Fees</th>
            <th className={s.th}>Trade Reason</th>
          </tr>
        </thead>
        <tbody>
          {Array.from(groupedTrades.entries()).map(([_oppId, group]) => {
            const isEven = groupIndex % 2 === 0;
            groupIndex++;

            return group.map((t, i) => {
              const rowClasses = [
                s.row,
                !isEven ? s.rowAlt : "",
                i === 0 && group.length > 1 ? s.rowGroupStart : "",
              ].filter(Boolean).join(" ");

              return (
                <tr key={t.id} className={rowClasses}>
                  <td className={s.td}>
                    {new Date(t.executed_at).toLocaleTimeString()}
                  </td>
                  <td className={s.td}>
                    <span className={`${s.sourceBadge} ${t.source === "live" ? s.sourceLive : s.sourcePaper}`}>
                      {t.source || "paper"}
                    </span>
                  </td>
                  <td className={s.tdMarket}>
                    {t.venue && t.venue !== "polymarket" && (
                      <span className={s.venueBadge}>{t.venue}</span>
                    )}
                    {t.market}
                  </td>
                  <td className={s.td}>{t.outcome}</td>
                  <td className={s.td}>
                    <span className={t.side === "BUY" ? s.sideBuy : s.sideSell}>
                      {t.side}
                    </span>
                  </td>
                  <td className={s.tdNum}>{t.size.toFixed(2)}</td>
                  <td className={s.tdNum}>{t.entry_price.toFixed(4)}</td>
                  <td className={s.tdNum}>{t.vwap_price.toFixed(4)}</td>
                  <td className={s.tdNum}>
                    {(t.slippage * 100).toFixed(2)}%
                  </td>
                  <td className={s.tdNum}>${t.fees.toFixed(4)}</td>
                  <td className={s.tdReason}>
                    {i === 0 ? formatTradeReason(group) : ""}
                  </td>
                </tr>
              );
            });
          })}
          {trades.length === 0 && (
            <tr>
              <td colSpan={11} className={s.empty}>
                No trades yet
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {/* Mobile card list */}
      <div className={s.cardList}>
        {trades.map((t) => (
          <div key={t.id} className={s.card}>
            <div className={s.cardHeader}>
              <span className={t.side === "BUY" ? s.sideBuy : s.sideSell}>{t.side}</span>
              <span className={`${s.sourceBadge} ${t.source === "live" ? s.sourceLive : s.sourcePaper}`}>
                {t.source || "paper"}
              </span>
              <span className={s.cardTime}>{new Date(t.executed_at).toLocaleTimeString()}</span>
            </div>
            <div className={s.cardMarket}>{t.market}</div>
            <div className={s.cardRow}>
              <span>{t.outcome}</span>
              <span className={s.cardMono}>{t.size.toFixed(2)} @ {t.vwap_price.toFixed(4)}</span>
            </div>
            <div className={s.cardRow}>
              <span className={s.cardLabel}>Impact</span>
              <span className={s.cardMono}>{(t.slippage * 100).toFixed(2)}%</span>
            </div>
          </div>
        ))}
        {trades.length === 0 && <div className={s.empty}>No trades yet</div>}
      </div>

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
