import React from "react";
import type { Position } from "../hooks/useDashboardData.ts";
import s from "./PositionsTable.module.css";

interface Props {
  positions: Position[];
}

const PositionsTable = React.memo(function PositionsTable({ positions }: Props) {
  const openCount = positions.filter((p) => !p.resolved).length;

  return (
    <div className={s.wrap}>
      <div className={s.explainer}>
        Open exposure from the latest portfolio snapshot. Each arb holds offsetting
        legs — a long and a short — so the basket nets to a hedged position.
      </div>
      <div className={s.summary}>
        {positions.length} position{positions.length === 1 ? "" : "s"} · {openCount} open
      </div>

      <table className={s.table}>
        <thead>
          <tr>
            <th className={s.th}>Market</th>
            <th className={s.th}>Outcome</th>
            <th className={s.th}>Side</th>
            <th className={s.thNum}>Shares</th>
            <th className={s.thNum}>Avg</th>
            <th className={s.thNum}>Cost Basis</th>
            <th className={s.th}>Status</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => {
            const long = p.shares >= 0;
            const absShares = Math.abs(p.shares);
            const avg =
              p.cost_basis != null && absShares > 0 ? p.cost_basis / absShares : null;
            return (
              <tr key={p.key} className={s.row}>
                <td className={s.tdMarket}>
                  {p.venue && p.venue !== "polymarket" && (
                    <span className={s.venueBadge}>{p.venue}</span>
                  )}
                  {p.market_question || `Market #${p.market_id}`}
                </td>
                <td className={s.td}>{p.outcome}</td>
                <td className={s.td}>
                  <span className={`${s.side} ${long ? s.long : s.short}`}>
                    {long ? "LONG" : "SHORT"}
                  </span>
                </td>
                <td className={s.tdNum}>{absShares.toFixed(1)}</td>
                <td className={s.tdNum}>{avg != null ? avg.toFixed(3) : "—"}</td>
                <td className={s.tdNum}>
                  {p.cost_basis != null ? `$${p.cost_basis.toFixed(2)}` : "—"}
                </td>
                <td className={s.td}>
                  {p.resolved ? (
                    <span className={s.resolved}>Resolved: {p.resolved_outcome}</span>
                  ) : (
                    <span className={s.openTag}>Open</span>
                  )}
                </td>
              </tr>
            );
          })}
          {positions.length === 0 && (
            <tr>
              <td colSpan={7} className={s.empty}>
                No open positions
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
});

export default PositionsTable;
