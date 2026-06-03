import React, { useCallback, useEffect, useState } from "react";
import type { Opportunity, ConstraintMatrix, TradeLeg } from "../hooks/useDashboardData.ts";
import CostWaterfall from "./CostWaterfall.tsx";
import s from "./OpportunityDetail.module.css";

interface Props {
  opportunity: Opportunity;
  onClose: () => void;
}

const OpportunityDetail = React.memo(function OpportunityDetail({
  opportunity: o,
  onClose,
}: Props) {
  const [closing, setClosing] = useState(false);

  const handleClose = useCallback(() => {
    setClosing(true);
    setTimeout(onClose, 200); // match animation duration
  }, [onClose]);

  // Close on Escape key
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") handleClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [handleClose]);

  const cm = o.pair?.constraint_matrix ?? null;
  const ot = o.optimal_trades ?? null;

  // Convergence quality (lower gap = better)
  const gapQuality = o.bregman_gap != null
    ? o.bregman_gap < 0.001 ? "Excellent"
    : o.bregman_gap < 0.01 ? "Good"
    : o.bregman_gap < 0.1 ? "Fair"
    : "Poor"
    : null;

  // Map bregman_gap to 0–100% bar using log scale.
  // gap=1e-6 -> 100%, gap=1e-3 -> 75%, gap=1e-1 -> 25%, gap=1 -> 0%
  const convergencePct = o.bregman_gap != null
    ? Math.max(0, Math.min(100, (-Math.log10(Math.max(o.bregman_gap, 1e-8)) / 6) * 100))
    : 0;

  return (
    <>
      <div className={`${s.overlay} ${closing ? s.overlayClosing : ""}`} onClick={handleClose} />
      <div className={`${s.panel} ${closing ? s.panelClosing : ""}`}>
        <div className={s.header}>
          <span className={s.headerTitle}>Opportunity Detail</span>
          <button className={s.closeBtn} onClick={handleClose}>&times;</button>
        </div>
        <div className={s.body}>
          {/* Status & Meta */}
          <div className={s.section}>
            <div className={s.sectionTitle}>Overview</div>
            <div className={s.kvGrid}>
              <div className={s.kvItem}>
                <span className={s.kvLabel}>Status</span>
                <span className={s.kvValue}>
                  <span className={`${s.badge} ${statusBadgeClass(o.status)}`}>
                    {o.status}
                  </span>
                </span>
              </div>
              <div className={s.kvItem}>
                <span className={s.kvLabel}>Type</span>
                <span className={s.kvValue}>{o.type}</span>
              </div>
              <div className={s.kvItem}>
                <span className={s.kvLabel}>Detected</span>
                <span className={s.kvValue}>
                  {o.timestamp ? new Date(o.timestamp).toLocaleString() : "\u2014"}
                </span>
              </div>
              <div className={s.kvItem}>
                <span className={s.kvLabel}>Dependency</span>
                <span className={s.kvValue}>
                  {o.pair?.dependency_type
                    ? formatDepType(o.pair.dependency_type)
                    : "\u2014"}
                </span>
              </div>
            </div>
          </div>

          {/* Markets */}
          <div className={s.section}>
            <div className={s.sectionTitle}>Markets</div>
            <div className={s.kvGrid}>
              <div className={s.kvItemFull}>
                <span className={s.kvLabel}>Market A</span>
                <span className={s.kvValueSmall}>
                  {o.pair?.market_a || "\u2014"}
                </span>
              </div>
              <div className={s.kvItemFull}>
                <span className={s.kvLabel}>Market B</span>
                <span className={s.kvValueSmall}>
                  {o.pair?.market_b || "\u2014"}
                </span>
              </div>
              {o.pair && (
                <div className={s.kvItem}>
                  <span className={s.kvLabel}>Confidence</span>
                  <span className={s.kvValueMono}>
                    {(o.pair.confidence * 100).toFixed(0)}%
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Proof: the logical relation + the concrete basket */}
          {(cm || (ot?.trades && ot.trades.length > 0)) && (
            <div className={s.section}>
              <div className={s.sectionTitle}>Proof of Arbitrage</div>
              <div className={s.relMeta}>
                <span className={s.relTag}>
                  {formatDepType(o.pair?.dependency_type ?? cm?.type ?? "")}
                </span>
                {o.pair?.verified != null && (
                  <span className={`${s.relTag} ${o.pair.verified ? s.relVerified : s.relUnverified}`}>
                    {o.pair.verified ? "verified" : "unverified"}
                  </span>
                )}
                {cm?.correlation && <span className={s.relDim}>corr {cm.correlation}</span>}
                {o.pair?.implication_direction && (
                  <span className={s.relDim}>impl {o.pair.implication_direction}</span>
                )}
                {o.pair?.classification_source && (
                  <span className={s.relDim}>src {o.pair.classification_source}</span>
                )}
              </div>

              {cm?.matrix && (
                <div className={s.proofBlock}>
                  <div className={s.proofCaption}>Feasible joint outcomes (A&darr; &times; B&rarr;)</div>
                  <ConstraintGrid cm={cm} />
                </div>
              )}

              {ot?.trades && ot.trades.length > 0 && (
                <div className={s.proofBlock}>
                  <div className={s.proofCaption}>Optimal basket</div>
                  <div className={s.basket}>
                    {ot.trades.map((leg, i) => (
                      <BasketLeg key={i} leg={leg} />
                    ))}
                  </div>
                  <div className={s.proofFootnote}>Locks profit across every feasible outcome</div>
                </div>
              )}
            </div>
          )}

          {/* Cost Waterfall */}
          <div className={s.section}>
            <div className={s.sectionTitle}>Cost Waterfall</div>
            <CostWaterfall theoretical={o.theoretical_profit} estimated={o.estimated_profit} />
          </div>

          {/* Optimizer Convergence */}
          {(o.fw_iterations != null || o.bregman_gap != null) && (
            <div className={s.section}>
              <div className={s.sectionTitle}>Frank-Wolfe Convergence</div>
              <div className={s.kvGrid}>
                <div className={s.kvItem}>
                  <span className={s.kvLabel}>Iterations</span>
                  <span className={s.kvValueMono}>
                    {o.fw_iterations ?? "\u2014"}
                  </span>
                </div>
                <div className={s.kvItem}>
                  <span className={s.kvLabel}>Bregman Gap</span>
                  <span className={s.kvValueMono}>
                    {o.bregman_gap != null ? o.bregman_gap.toFixed(6) : "\u2014"}
                  </span>
                </div>
              </div>
              {gapQuality && (
                <div className={s.convergenceBar}>
                  <div className={s.convergenceTrack}>
                    <div
                      className={s.convergenceFill}
                      style={{ width: `${convergencePct}%` }}
                    />
                  </div>
                  <span className={s.convergenceLabel}>{gapQuality}</span>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  );
});

export default OpportunityDetail;

function formatDepType(dt: string): string {
  return dt
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function statusBadgeClass(status: string): string {
  switch (status) {
    case "detected":    return s.statusDetected;
    case "optimized":   return s.statusOptimized;
    case "simulated":   return s.statusSimulated;
    case "unconverged": return s.statusUnconverged;
    default:            return "";
  }
}

// Feasibility grid: rows = Market A outcomes, cols = Market B outcomes.
// A cell is feasible (✓) when that joint outcome can occur under the relation.
function ConstraintGrid({ cm }: { cm: ConstraintMatrix }) {
  return (
    <table className={s.matrix}>
      <thead>
        <tr>
          <th className={s.matrixCorner}>{"A\\B"}</th>
          {cm.outcomes_b.map((b, j) => (
            <th key={j} className={s.matrixHead}>{b}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {cm.outcomes_a.map((a, i) => (
          <tr key={i}>
            <th className={s.matrixRowHead}>{a}</th>
            {cm.outcomes_b.map((_b, j) => {
              const feasible = cm.matrix?.[i]?.[j] === 1;
              return (
                <td key={j} className={`${s.matrixCell} ${feasible ? s.feasible : s.infeasible}`}>
                  {feasible ? "✓" : "✕"}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// One leg of the optimal basket: side, market+outcome, market vs fair price, edge.
function BasketLeg({ leg }: { leg: TradeLeg }) {
  const buy = (leg.side ?? "").toUpperCase() === "BUY";
  return (
    <div className={s.leg}>
      <span className={`${s.legSide} ${buy ? s.legBuy : s.legSell}`}>{leg.side}</span>
      <span className={s.legMkt}>{leg.market} &middot; {leg.outcome}</span>
      {leg.venue && leg.venue !== "polymarket" && <span className={s.legVenue}>{leg.venue}</span>}
      <span className={s.legSpacer} />
      <span className={s.legPrice}>@{leg.market_price.toFixed(3)}</span>
      <span className={s.legFair}>fair {leg.fair_price.toFixed(3)}</span>
      <span
        className={s.legEdge}
        style={{ color: leg.edge >= 0 ? "var(--color-green)" : "var(--color-red)" }}
      >
        {leg.edge >= 0 ? "+" : "−"}{Math.abs(leg.edge).toFixed(3)}
      </span>
    </div>
  );
}
