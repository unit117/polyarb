import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../hooks.ts";
import s from "./MetricsPanel.module.css";

interface FunnelData {
  funnel: {
    detected: number;
    optimized: number;
    simulated: number;
    traded: number;
  };
  status_breakdown: Record<string, number>;
}

interface DepTypeRow {
  dependency_type: string;
  total_opportunities: number;
  simulated: number;
  hit_rate: number;
  avg_theoretical_profit: number;
  avg_estimated_profit: number;
}

interface DurationData {
  total_expired: number;
  avg_duration_seconds: number;
  median_duration_seconds: number;
  histogram: Record<string, number>;
}

interface TimeseriesPoint {
  hour: string;
  detected?: number;
  trades?: number;
  fees?: number;
  volume?: number;
  expired?: number;
}

export default function MetricsPanel() {
  const [funnel, setFunnel] = useState<FunnelData | null>(null);
  const [depTypes, setDepTypes] = useState<DepTypeRow[]>([]);
  const [duration, setDuration] = useState<DurationData | null>(null);
  const [timeseries, setTimeseries] = useState<TimeseriesPoint[]>([]);

  const refresh = useCallback(() => {
    apiFetch<FunnelData>("/metrics/funnel?hours=24").then(setFunnel).catch(console.error);
    apiFetch<{ by_dependency_type: DepTypeRow[] }>("/metrics/by-dependency-type?hours=24")
      .then((r) => setDepTypes(r.by_dependency_type))
      .catch(console.error);
    apiFetch<DurationData>("/metrics/duration?hours=168").then(setDuration).catch(console.error);
    apiFetch<{ timeseries: TimeseriesPoint[] }>("/metrics/timeseries?hours=24")
      .then((r) => setTimeseries(r.timeseries))
      .catch(console.error);
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 60_000);
    return () => clearInterval(interval);
  }, [refresh]);

  return (
    <div className={s.wrap}>
      {/* Opportunity Funnel */}
      <section className={s.section}>
        <h3 className={s.sectionTitle}>Opportunity Funnel (24h)</h3>
        {funnel && (
          <div className={s.funnel}>
            {(["detected", "optimized", "simulated", "traded"] as const).map((stage, i) => {
              const count = funnel.funnel[stage];
              const prev = i > 0 ? funnel.funnel[(["detected", "optimized", "simulated", "traded"] as const)[i - 1]] : count;
              const pct = prev > 0 ? Math.round((count / prev) * 100) : 0;
              return (
                <div key={stage} className={s.funnelStage}>
                  <div className={s.funnelBar} style={{ width: `${Math.max(10, (count / Math.max(funnel.funnel.detected, 1)) * 100)}%` }} />
                  <div className={s.funnelLabel}>
                    <span className={s.funnelName}>{stage}</span>
                    <span className={s.funnelCount}>{count.toLocaleString()}</span>
                    {i > 0 && <span className={s.funnelPct}>{pct}%</span>}
                  </div>
                </div>
              );
            })}
          </div>
        )}
        {funnel && (
          <div className={s.breakdown}>
            <span className={s.breakdownTitle}>Status breakdown:</span>
            {Object.entries(funnel.status_breakdown).map(([status, count]) => (
              <span key={status} className={s.breakdownItem}>
                {status}: {count}
              </span>
            ))}
          </div>
        )}
      </section>

      {/* By Dependency Type */}
      <section className={s.section}>
        <h3 className={s.sectionTitle}>Hit Rate by Dependency Type (24h)</h3>
        <table className={s.table}>
          <thead>
            <tr>
              <th className={s.th}>Type</th>
              <th className={s.th}>Opportunities</th>
              <th className={s.th}>Simulated</th>
              <th className={s.th}>Hit Rate</th>
              <th className={s.th}>Avg Theo. Profit</th>
              <th className={s.th}>Avg Est. Profit</th>
            </tr>
          </thead>
          <tbody>
            {depTypes.map((row) => (
              <tr key={row.dependency_type} className={s.row}>
                <td className={s.td}>{row.dependency_type}</td>
                <td className={s.tdNum}>{row.total_opportunities}</td>
                <td className={s.tdNum}>{row.simulated}</td>
                <td className={s.tdNum}>{(row.hit_rate * 100).toFixed(1)}%</td>
                <td className={s.tdNum}>{row.avg_theoretical_profit.toFixed(4)}</td>
                <td className={s.tdNum}>{row.avg_estimated_profit.toFixed(4)}</td>
              </tr>
            ))}
            {depTypes.length === 0 && (
              <tr><td colSpan={6} className={s.empty}>No data</td></tr>
            )}
          </tbody>
        </table>
      </section>

      {/* Duration Histogram */}
      <section className={s.section}>
        <h3 className={s.sectionTitle}>Opportunity Duration (7d)</h3>
        {duration && duration.total_expired > 0 ? (
          <>
            <div className={s.durationStats}>
              <span>Total expired: <strong>{duration.total_expired}</strong></span>
              <span>Avg: <strong>{formatDuration(duration.avg_duration_seconds)}</strong></span>
              <span>Median: <strong>{formatDuration(duration.median_duration_seconds)}</strong></span>
            </div>
            <div className={s.histogram}>
              {Object.entries(duration.histogram).map(([bucket, count]) => {
                const maxCount = Math.max(...Object.values(duration.histogram));
                return (
                  <div key={bucket} className={s.histBar}>
                    <span className={s.histLabel}>{bucket}</span>
                    <div className={s.histTrack}>
                      <div
                        className={s.histFill}
                        style={{ width: `${maxCount > 0 ? (count / maxCount) * 100 : 0}%` }}
                      />
                    </div>
                    <span className={s.histCount}>{count}</span>
                  </div>
                );
              })}
            </div>
          </>
        ) : (
          <p className={s.empty}>No expired opportunities yet</p>
        )}
      </section>

      {/* Hourly Timeseries */}
      <section className={s.section}>
        <h3 className={s.sectionTitle}>Hourly Activity (24h)</h3>
        <table className={s.table}>
          <thead>
            <tr>
              <th className={s.th}>Hour</th>
              <th className={s.th}>Detected</th>
              <th className={s.th}>Trades</th>
              <th className={s.th}>Fees</th>
              <th className={s.th}>Volume</th>
              <th className={s.th}>Expired</th>
            </tr>
          </thead>
          <tbody>
            {timeseries.slice(-24).map((point) => (
              <tr key={point.hour} className={s.row}>
                <td className={s.td}>{new Date(point.hour).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</td>
                <td className={s.tdNum}>{point.detected ?? 0}</td>
                <td className={s.tdNum}>{point.trades ?? 0}</td>
                <td className={s.tdNum}>{(point.fees ?? 0).toFixed(2)}</td>
                <td className={s.tdNum}>{(point.volume ?? 0).toFixed(2)}</td>
                <td className={s.tdNum}>{point.expired ?? 0}</td>
              </tr>
            ))}
            {timeseries.length === 0 && (
              <tr><td colSpan={6} className={s.empty}>No data</td></tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}
