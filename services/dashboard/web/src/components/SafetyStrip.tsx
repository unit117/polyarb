import { useCallback, useEffect, useState } from "react";
import { apiFetch, apiPost } from "../hooks.ts";
import s from "./SafetyStrip.module.css";

interface LiveStatus {
  configured: boolean;
  enabled: boolean;
  dry_run: boolean;
  active: boolean;
  kill_switch: boolean;
  runtime_fresh: boolean;
  bankroll: number;
  max_position_size: number;
  min_edge: number;
  order_count: number;
  fill_count: number;
}

/**
 * Live-trading control + state. The kill switch (/live/kill) and re-enable
 * (/live/enable) endpoints exist but had no UI. Rendered only in Live mode.
 */
export default function SafetyStrip() {
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => {
    apiFetch<LiveStatus>("/live/status").then(setStatus).catch(console.error);
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 15000);
    return () => clearInterval(t);
  }, [refresh]);

  const kill = useCallback(() => {
    if (!window.confirm("Kill live trading now? Sets the kill switch and halts all live orders.")) return;
    setBusy(true);
    apiPost("/live/kill").then(refresh).catch(console.error).finally(() => setBusy(false));
  }, [refresh]);

  const enable = useCallback(() => {
    if (!window.confirm("Re-enable live trading? This clears the kill switch.")) return;
    setBusy(true);
    apiPost("/live/enable").then(refresh).catch(console.error).finally(() => setBusy(false));
  }, [refresh]);

  if (!status) {
    return (
      <div className={s.strip}>
        <span className={s.loading}>Loading live status…</span>
      </div>
    );
  }

  const state = status.kill_switch
    ? { label: "Kill-switched", cls: s.killed }
    : status.active
      ? { label: "Active", cls: s.active }
      : status.enabled
        ? { label: "Enabled · idle", cls: s.idle }
        : { label: "Disabled", cls: s.disabled };

  return (
    <div className={s.strip}>
      <div className={s.left}>
        <span className={`${s.statePill} ${state.cls}`}>
          {status.active && <span className={s.pulse} />}
          {state.label}
        </span>
        {status.dry_run && <span className={s.tag}>dry-run</span>}
        {!status.configured && <span className={s.tagWarn}>not configured</span>}
        <span className={`${s.tag} ${status.runtime_fresh ? s.fresh : s.stale}`}>
          {status.runtime_fresh ? "heartbeat ok" : "no heartbeat"}
        </span>
      </div>

      <div className={s.metrics}>
        <Metric label="bankroll" value={`$${status.bankroll.toFixed(0)}`} />
        <Metric label="max pos" value={`$${status.max_position_size.toFixed(0)}`} />
        <Metric label="min edge" value={`${(status.min_edge * 100).toFixed(1)}%`} />
        <Metric label="orders" value={String(status.order_count)} />
        <Metric label="fills" value={String(status.fill_count)} />
      </div>

      <div className={s.actions}>
        {status.kill_switch ? (
          <button className={`${s.btn} ${s.btnEnable}`} onClick={enable} disabled={busy}>
            Re-enable
          </button>
        ) : status.active || status.enabled ? (
          <button className={`${s.btn} ${s.btnKill}`} onClick={kill} disabled={busy}>
            Kill
          </button>
        ) : null}
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className={s.metric}>
      <span className={s.metricLabel}>{label}</span>
      <span className={s.metricValue}>{value}</span>
    </div>
  );
}
