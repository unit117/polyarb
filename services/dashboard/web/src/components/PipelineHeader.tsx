import React, { useEffect, useState } from "react";
import type { Stats, FunnelData, TapeEvent, Opportunity, Pair } from "../hooks/useDashboardData.ts";
import s from "./PipelineHeader.module.css";

type DotStatus = "live" | "ok" | "idle" | "warn" | "alert";

interface Props {
  stats: Stats | null;
  funnel: FunnelData | null;
  events: TapeEvent[];
  opportunities: Opportunity[];
  pairs: Pair[];
  onCellClick?: (tab: string) => void;
}

interface Line {
  label: string;
  value: string;
  color?: string;
}

interface CellData {
  stage: string;
  status: DotStatus;
  primary: string;
  primaryLabel: string;
  lines: Line[];
  onClick?: () => void;
  title?: string;
  accent?: string;
}

/**
 * The pipeline as it actually runs: Ingest -> Detect -> Optimize -> Simulate -> Portfolio.
 * Cumulative counts come from REST (/stats, /metrics/funnel); live rates and freshness
 * are derived from the Redis event buffer. A 1s ticker keeps "age" fields moving so a
 * stalled stage visibly decays to amber/red instead of silently flatlining.
 */
const PipelineHeader = React.memo(function PipelineHeader({
  stats,
  funnel,
  events,
  opportunities,
  pairs,
  onCellClick,
}: Props) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const f = funnel?.funnel;
  const p = stats?.portfolio ?? null;

  // ── Ingest ──
  const snapEvents = events.filter((e) => e.kind === "snapshot");
  const lastSnap = snapEvents[0];
  const snapAgeMs = lastSnap ? now - lastSnap.ts : null;
  const snapsLastMin = snapEvents
    .filter((e) => now - e.ts < 60_000)
    .reduce((sum, e) => sum + (num(e.data.count) ?? 0), 0);
  const feed = lastSnap ? String(lastSnap.data.source ?? "") : "";

  // ── Detect ──
  const pairEvents = events.filter((e) => e.kind === "pair");
  const recentPairTimes = pairs
    .map((p) => Date.parse(p.detected_at))
    .filter((ts) => Number.isFinite(ts));
  const lastPairAge = pairEvents[0]
    ? now - pairEvents[0].ts
    : recentPairTimes.length
      ? now - Math.max(...recentPairTimes)
      : null;
  const pairsLastHour = pairEvents.length
    ? pairEvents.filter((e) => now - e.ts < 3_600_000).length
    : recentPairTimes.filter((ts) => now - ts < 3_600_000).length;

  // ── Optimize ── (rolling over the most recent optimizer outputs)
  const optEvents = events.filter((e) => e.kind === "optimize").slice(0, 50);
  const optRows = optEvents.length
    ? optEvents.map((e) => ({
      converged: e.data.converged === true,
      iterations: num(e.data.iterations),
      gap: num(e.data.bregman_gap),
    }))
    : opportunities
      .filter((o) => o.fw_iterations != null || o.bregman_gap != null)
      .slice(0, 50)
      .map((o) => ({
        converged: o.status !== "unconverged",
        iterations: o.fw_iterations,
        gap: o.bregman_gap,
      }));
  const convergedPct = optEvents.length
    ? (optRows.filter((e) => e.converged).length / optRows.length) * 100
    : f?.detected
      ? (f.optimized / f.detected) * 100
      : optRows.length
        ? (optRows.filter((e) => e.converged).length / optRows.length) * 100
    : null;
  const medIters = median(optRows.map((e) => e.iterations).filter(isNum));
  const medGap = median(optRows.map((e) => e.gap).filter(isNum));

  // ── Simulate ──
  const cbEvent = events.find((e) => e.kind === "circuit");
  const cbActive = cbEvent ? now - cbEvent.ts < 600_000 : false;
  const passRate = f && f.detected ? (f.traded / f.detected) * 100 : null;

  // ── Portfolio ──
  const totalPnl = p ? p.total_pnl : null;
  const winRate = p && p.settled_trades > 0 ? (p.winning_trades / p.settled_trades) * 100 : null;

  const ingestDot: DotStatus =
    snapAgeMs == null ? "idle" : snapAgeMs < 120_000 ? "live" : snapAgeMs < 600_000 ? "warn" : "alert";

  const cells: CellData[] = [
    {
      stage: "Ingest",
      status: ingestDot,
      primary: fmtNum(stats?.active_markets),
      primaryLabel: "active markets",
      title: feed ? `Price feed: ${feed}` : "Market ingestion",
      lines: [
        { label: "snaps/min", value: snapsLastMin ? fmtNum(snapsLastMin) : "—" },
        { label: "last tick", value: fmtAge(snapAgeMs) },
        { label: "feed", value: feed || "—" },
      ] as Line[],
    },
    {
      stage: "Detect",
      status: stats?.market_pairs ? "ok" : "idle",
      primary: fmtNum(stats?.market_pairs),
      primaryLabel: "market pairs",
      onClick: () => onCellClick?.("pairs"),
      title: "Correlated pairs found by the detector",
      lines: [
        { label: "+1h", value: pairsLastHour ? `+${pairsLastHour}` : "0" },
        { label: "last", value: fmtAge(lastPairAge) },
      ] as Line[],
    },
    {
      stage: "Optimize",
      status: optEvents.length ? "live" : f?.detected ? "ok" : "idle",
      primary: fmtPct(convergedPct),
      primaryLabel: "converged",
      onClick: () => onCellClick?.("opportunities"),
      title: "Frank-Wolfe optimizer convergence (rolling)",
      lines: [
        { label: "det→opt", value: `${fmtNum(f?.detected)}→${fmtNum(f?.optimized)}` },
        { label: "med iters", value: medIters == null ? "—" : String(Math.round(medIters)) },
        { label: "med gap", value: medGap == null ? "—" : medGap.toExponential(1) },
      ] as Line[],
    },
    {
      stage: "Simulate",
      status: cbActive ? "alert" : passRate ? "live" : f?.optimized ? "warn" : "idle",
      primary: fmtPct(passRate),
      primaryLabel: "pass-through",
      onClick: () => onCellClick?.("trades"),
      title: "Risk-gated execution: opportunities that became trades",
      lines: [
        { label: "simulated", value: fmtNum(f?.simulated) },
        { label: "traded", value: fmtNum(f?.traded) },
        cbActive
          ? { label: "circuit", value: "TRIPPED", color: "var(--color-red)" }
          : { label: "circuit", value: "OK", color: "var(--color-green)" },
      ] as Line[],
    },
    {
      stage: "Portfolio",
      status: totalPnl == null ? "idle" : totalPnl >= 0 ? "live" : "warn",
      primary: p ? `$${p.total_value.toFixed(2)}` : "—",
      primaryLabel: "total value",
      accent: totalPnl == null ? undefined : totalPnl >= 0 ? "var(--color-green)" : "var(--color-red)",
      title: "Paper/live portfolio value",
      lines: [
        {
          label: "PnL",
          value: totalPnl == null ? "—" : `${totalPnl >= 0 ? "+" : "−"}$${Math.abs(totalPnl).toFixed(2)}`,
          color: totalPnl == null ? undefined : totalPnl >= 0 ? "var(--color-green)" : "var(--color-red)",
        },
        { label: "positions", value: fmtNum(p?.total_positions) },
        { label: "win rate", value: winRate == null ? "—" : `${winRate.toFixed(0)}%` },
      ] as Line[],
    },
  ];

  return (
    <div className={s.header}>
      {cells.map((c, i) => (
        <React.Fragment key={c.stage}>
          {i > 0 && <div className={s.arrow} aria-hidden>→</div>}
          <Cell {...c} />
        </React.Fragment>
      ))}
    </div>
  );
});

export default PipelineHeader;

function Cell({
  stage,
  status,
  primary,
  primaryLabel,
  lines,
  onClick,
  title,
  accent,
}: {
  stage: string;
  status: DotStatus;
  primary: string;
  primaryLabel: string;
  lines: Line[];
  onClick?: () => void;
  title?: string;
  accent?: string;
}) {
  return (
    <div
      className={`${s.cell} ${onClick ? s.clickable : ""}`}
      onClick={onClick}
      title={title}
    >
      <div className={s.cellHead}>
        <span className={`${s.dot} ${s[`dot_${status}`]}`} />
        <span className={s.stage}>{stage}</span>
      </div>
      <div className={s.primary} style={accent ? { color: accent } : undefined}>
        {primary}
      </div>
      <div className={s.primaryLabel}>{primaryLabel}</div>
      <div className={s.lines}>
        {lines.map((ln, i) => (
          <div key={i} className={s.line}>
            <span className={s.lineLabel}>{ln.label}</span>
            <span className={s.lineValue} style={ln.color ? { color: ln.color } : undefined}>
              {ln.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── helpers ──
function num(v: unknown): number | null {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
function isNum(v: number | null): v is number {
  return v != null;
}
function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const sorted = [...xs].sort((a, b) => a - b);
  const m = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[m] : (sorted[m - 1] + sorted[m]) / 2;
}
function fmtNum(n: number | null | undefined): string {
  return n == null ? "—" : n.toLocaleString();
}
function fmtPct(n: number | null): string {
  return n == null ? "—" : `${n.toFixed(0)}%`;
}
function fmtAge(ms: number | null): string {
  if (ms == null) return "—";
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m`;
  return `${Math.floor(sec / 3600)}h`;
}
