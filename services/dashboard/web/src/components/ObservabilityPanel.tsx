import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../hooks.ts";
import s from "./ObservabilityPanel.module.css";

interface TopPair {
  pair_id: number;
  trades_7d: number;
  gross_7d: number;
  share_pct: number | null;
}

interface ObservabilityData {
  counters_by_day: Record<string, Record<string, number>>;
  breaker: Record<string, string | number | null>;
  cooldowns_active: number;
  top_pairs_7d: TopPair[];
  total_gross_7d: number;
  trades_captured_24h: number;
  classification_cache_rows: number;
  table_bytes: Record<string, number>;
  database_bytes: number;
  disk: { total: number; free: number };
}

const COUNTER_LABELS: Record<string, string> = {
  cooldown_rejections_recorded: "Cooldown rejections recorded",
  cooldowns_started: "Cooldowns started",
  pair_flow_cap_rejections: "Flow-cap rejections",
  startup_grace_skips: "Startup-grace skips",
  llm_classification_errors: "LLM classification errors",
  snapshot_partial_skips: "Partial snapshots refused",
  snapshot_cap_truncations: "Snapshot cap truncations",
  ws_trades_flushed: "Trades captured (WS)",
  ws_trade_flush_errors: "Trade flush errors",
  poll_cycle_seconds: "Poll cycle (s, latest)",
};

function gb(bytes: number): string {
  return (bytes / 1024 ** 3).toFixed(1) + " GB";
}

export default function ObservabilityPanel() {
  const [data, setData] = useState<ObservabilityData | null>(null);

  const refresh = useCallback(() => {
    apiFetch<ObservabilityData>("/metrics/observability?days=7")
      .then(setData)
      .catch(console.error);
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 60_000);
    return () => clearInterval(interval);
  }, [refresh]);

  if (!data) return null;

  const days = Object.keys(data.counters_by_day).sort().reverse().slice(0, 3);
  const names = Array.from(
    new Set(days.flatMap((d) => Object.keys(data.counters_by_day[d] ?? {})))
  ).sort();

  const breakerBad =
    data.breaker.paper_trip || data.breaker.live_trip || data.breaker.kill_switch;

  return (
    <div className={s.wrap}>
      <section className={s.section}>
        <h3 className={s.sectionTitle}>System State</h3>
        <div className={s.chips}>
          <span className={breakerBad ? s.chipBad : s.chipOk}>
            Breaker:{" "}
            {String(data.breaker.paper_trip ?? data.breaker.live_trip ?? "armed, not tripped")}
          </span>
          <span className={s.chip}>
            Paper daily loss: ${Number(data.breaker.paper_daily_loss ?? 0).toFixed(2)}
          </span>
          <span className={data.breaker.kill_switch ? s.chipBad : s.chipOk}>
            Kill switch: {String(data.breaker.kill_switch ?? "off")}
          </span>
          <span className={s.chip}>Active cooldowns: {data.cooldowns_active}</span>
          <span className={s.chip}>
            Tape (24h): {data.trades_captured_24h.toLocaleString()} trades
          </span>
        </div>
      </section>

      <section className={s.section}>
        <h3 className={s.sectionTitle}>Safety Mechanisms (daily counters)</h3>
        <table className={s.table}>
          <thead>
            <tr>
              <th className={s.th}>Metric</th>
              {days.map((d) => (
                <th key={d} className={s.thNum}>
                  {d.slice(4, 6)}/{d.slice(6, 8)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {names.map((name) => (
              <tr key={name} className={s.row}>
                <td className={s.td}>{COUNTER_LABELS[name] ?? name}</td>
                {days.map((d) => (
                  <td key={d} className={s.tdNum}>
                    {(data.counters_by_day[d]?.[name] ?? 0).toLocaleString()}
                  </td>
                ))}
              </tr>
            ))}
            {names.length === 0 && (
              <tr>
                <td colSpan={days.length + 1} className={s.empty}>
                  No counters yet
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      <section className={s.section}>
        <h3 className={s.sectionTitle}>
          Pair Concentration (7d gross ${data.total_gross_7d.toLocaleString()})
        </h3>
        <table className={s.table}>
          <thead>
            <tr>
              <th className={s.th}>Pair</th>
              <th className={s.thNum}>Trades</th>
              <th className={s.thNum}>Gross $</th>
              <th className={s.thNum}>Share</th>
            </tr>
          </thead>
          <tbody>
            {data.top_pairs_7d.map((p) => (
              <tr key={p.pair_id} className={s.row}>
                <td className={s.td}>{p.pair_id}</td>
                <td className={s.tdNum}>{p.trades_7d}</td>
                <td className={s.tdNum}>{p.gross_7d.toFixed(2)}</td>
                <td className={p.share_pct !== null && p.share_pct > 15 ? s.tdWarn : s.tdNum}>
                  {p.share_pct !== null ? `${p.share_pct}%` : "—"}
                </td>
              </tr>
            ))}
            {data.top_pairs_7d.length === 0 && (
              <tr>
                <td colSpan={4} className={s.empty}>
                  No trades in window
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      <section className={s.section}>
        <h3 className={s.sectionTitle}>Storage</h3>
        <div className={s.chips}>
          <span className={s.chip}>DB: {gb(data.database_bytes)}</span>
          {Object.entries(data.table_bytes)
            .sort((a, b) => b[1] - a[1])
            .map(([t, b]) => (
              <span key={t} className={s.chip}>
                {t}: {gb(b)}
              </span>
            ))}
          <span className={data.disk.free < 0.1 * data.disk.total ? s.chipBad : s.chipOk}>
            Disk free: {gb(data.disk.free)}
          </span>
          <span className={s.chip}>
            Classifier cache: {data.classification_cache_rows.toLocaleString()} rows
          </span>
        </div>
      </section>
    </div>
  );
}
