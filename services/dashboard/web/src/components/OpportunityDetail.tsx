import React, { useEffect } from "react";
import type { Opportunity } from "../hooks/useDashboardData.ts";
import s from "./OpportunityDetail.module.css";

interface Props {
  opportunity: Opportunity;
  onClose: () => void;
}

const OpportunityDetail = React.memo(function OpportunityDetail({
  opportunity: o,
  onClose,
}: Props) {
  // Close on Escape key
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  const profitDelta = o.theoretical_profit - o.estimated_profit;
  const feesImpact = o.theoretical_profit > 0
    ? ((profitDelta / o.theoretical_profit) * 100).toFixed(1)
    : "0";

  // Convergence quality (lower gap = better)
  const gapQuality = o.bregman_gap != null
    ? o.bregman_gap < 0.001 ? "Excellent"
    : o.bregman_gap < 0.01 ? "Good"
    : o.bregman_gap < 0.1 ? "Fair"
    : "Poor"
    : null;

  const convergencePct = o.bregman_gap != null
    ? Math.max(0, Math.min(100, 100 - Math.log10(Math.max(o.bregman_gap, 1e-8)) * 12.5))
    : 0;

  return (
    <>
      <div className={s.overlay} onClick={onClose} />
      <div className={s.panel}>
        <div className={s.header}>
          <span className={s.headerTitle}>Opportunity Detail</span>
          <button className={s.closeBtn} onClick={onClose}>&times;</button>
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
                    ? o.pair.dependency_type.replace(/_/g, " ")
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

          {/* Profit Comparison */}
          <div className={s.section}>
            <div className={s.sectionTitle}>Profit Analysis</div>
            <div className={s.profitCompare}>
              <div className={s.profitBox}>
                <div className={s.profitBoxLabel}>Theoretical</div>
                <div
                  className={s.profitBoxValue}
                  style={{ color: o.theoretical_profit > 0 ? "var(--color-green)" : "var(--color-text-dim)" }}
                >
                  {o.theoretical_profit.toFixed(4)}
                </div>
              </div>
              <div className={s.profitBoxArrow}>&rarr;</div>
              <div className={s.profitBox}>
                <div className={s.profitBoxLabel}>After Fees</div>
                <div
                  className={s.profitBoxValue}
                  style={{
                    color: o.estimated_profit > 0.01
                      ? "var(--color-green)"
                      : o.estimated_profit > 0
                        ? "var(--color-yellow)"
                        : "var(--color-text-dim)",
                  }}
                >
                  {o.estimated_profit.toFixed(4)}
                </div>
              </div>
            </div>
            <div className={s.kvGrid} style={{ marginTop: 12 }}>
              <div className={s.kvItem}>
                <span className={s.kvLabel}>Fee Impact</span>
                <span className={s.kvValueMono} style={{ color: "var(--color-red)" }}>
                  -{feesImpact}%
                </span>
              </div>
              <div className={s.kvItem}>
                <span className={s.kvLabel}>Fees + Slippage</span>
                <span className={s.kvValueMono}>
                  {profitDelta.toFixed(4)}
                </span>
              </div>
            </div>
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

function statusBadgeClass(status: string): string {
  switch (status) {
    case "detected":    return s.statusDetected;
    case "optimized":   return s.statusOptimized;
    case "simulated":   return s.statusSimulated;
    case "unconverged": return s.statusUnconverged;
    default:            return "";
  }
}
