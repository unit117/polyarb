import React, { useEffect, useState } from "react";
import type { TapeEvent, EventStage } from "../hooks/useDashboardData.ts";
import { TAPE_KINDS } from "../hooks/useDashboardData.ts";
import s from "./LiveTape.module.css";

interface Props {
  events: TapeEvent[];
  connected: boolean;
}

type Filter = EventStage | "all";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "detect", label: "Detect" },
  { key: "optimize", label: "Optimize" },
  { key: "simulate", label: "Simulate" },
  { key: "settle", label: "Settle" },
];

/**
 * The pipeline's event bus, made visible. Renders the WS payloads the dashboard
 * already receives (and previously discarded) as a trading-floor tape. Newest at
 * top; hovering pauses updates so a row can be read without it scrolling away.
 */
const LiveTape = React.memo(function LiveTape({ events, connected }: Props) {
  const [filter, setFilter] = useState<Filter>("all");
  const [paused, setPaused] = useState(false);
  const [frozen, setFrozen] = useState<TapeEvent[]>([]);

  // Snapshot the feed the instant we pause so the visible rows hold still.
  useEffect(() => {
    if (paused) setFrozen(events);
    // Only re-snapshot when pause toggles on, not on every new event.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paused]);

  const source = paused ? frozen : events;
  const rows = source
    .filter((e) => TAPE_KINDS.has(e.kind) && (filter === "all" || e.stage === filter))
    .slice(0, 150);

  return (
    <div className={s.tape}>
      <div className={s.head}>
        <span className={s.title}>
          <span className={`${s.conn} ${connected ? s.connOn : s.connOff}`} />
          Live Tape
        </span>
        <span className={s.status}>{paused ? "paused" : connected ? "streaming" : "offline"}</span>
      </div>

      <div className={s.filters}>
        {FILTERS.map((fl) => (
          <button
            key={fl.key}
            className={`${s.chip} ${filter === fl.key ? s.chipActive : ""}`}
            onClick={() => setFilter(fl.key)}
          >
            {fl.label}
          </button>
        ))}
      </div>

      <div
        className={s.body}
        onMouseEnter={() => setPaused(true)}
        onMouseLeave={() => setPaused(false)}
      >
        {rows.length === 0 ? (
          <div className={s.empty}>
            {connected ? "No live pipeline events since this page opened" : "Disconnected — reconnecting…"}
          </div>
        ) : (
          rows.map((e) => <Row key={e.id} event={e} />)
        )}
      </div>
    </div>
  );
});

export default LiveTape;

const Row = React.memo(function Row({ event }: { event: TapeEvent }) {
  const { icon, text, color } = describe(event);
  return (
    <div className={s.row} style={{ borderLeftColor: color }}>
      <span className={s.time}>{fmtTime(event.ts)}</span>
      <span className={s.icon}>{icon}</span>
      <span className={s.text}>{text}</span>
    </div>
  );
});

interface Described {
  icon: string;
  text: string;
  color: string;
}

const STAGE_COLOR: Record<EventStage, string> = {
  ingest: "var(--color-text-dim)",
  detect: "var(--color-blue)",
  optimize: "var(--color-blue-light)",
  simulate: "var(--color-green)",
  settle: "var(--color-yellow)",
  portfolio: "var(--color-text-dim)",
};

function describe(e: TapeEvent): Described {
  const d = e.data;
  const color = STAGE_COLOR[e.stage];
  switch (e.kind) {
    case "pair":
      return {
        icon: "🔗",
        color,
        text: `${depType(d.dependency_type)} pair · conf ${pct(d.confidence)}`,
      };
    case "arb":
      return {
        icon: "✨",
        color,
        text: `arb found · ${depType(d.type)} · theo ${money(d.theoretical_profit)}`,
      };
    case "optimize": {
      const converged = d.converged === true;
      const iters = numOrNull(d.iterations);
      if (!converged) {
        return {
          icon: "⚙️",
          color: "var(--color-yellow)",
          text: `unconverged${iters != null ? ` · ${iters} iters` : ""} · ${depStatus(d.status)}`,
        };
      }
      return {
        icon: "⚙️",
        color,
        text: `optimized · ${iters ?? "?"} iters · gap ${expo(d.bregman_gap)} · est ${money(d.estimated_profit)}`,
      };
    }
    case "trade": {
      const side = String(d.side ?? "").toUpperCase();
      return {
        icon: side === "SELL" ? "🔻" : "✅",
        color,
        text: `${side || "TRADE"} ${numOrNull(d.size) ?? "?"} @ ${price(d.vwap_price)} · slip ${pct(d.slippage)}`,
      };
    }
    case "circuit":
      return {
        icon: "🟥",
        color: "var(--color-red)",
        text: `circuit breaker tripped${d.reason ? ` · ${String(d.reason)}` : ""}`,
      };
    case "resolved":
      return {
        icon: "🏁",
        color,
        text: `market resolved ${String(d.resolved_outcome ?? "")}${d.source ? ` (${String(d.source)})` : ""}`,
      };
    default:
      return { icon: "•", color, text: e.channel };
  }
}

// ── formatting helpers ──
function numOrNull(v: unknown): number | null {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
function depType(v: unknown): string {
  return v ? String(v).replace(/_/g, " ") : "?";
}
function depStatus(v: unknown): string {
  return v ? String(v) : "skipped";
}
function pct(v: unknown): string {
  const n = numOrNull(v);
  return n == null ? "—" : `${(n * 100).toFixed(n < 0.1 ? 1 : 0)}%`;
}
function money(v: unknown): string {
  const n = numOrNull(v);
  if (n == null) return "—";
  return `${n >= 0 ? "+" : "−"}$${Math.abs(n).toFixed(4)}`;
}
function price(v: unknown): string {
  const n = numOrNull(v);
  return n == null ? "—" : n.toFixed(3);
}
function expo(v: unknown): string {
  const n = numOrNull(v);
  return n == null ? "—" : n.toExponential(1);
}
function fmtTime(ts: number): string {
  return new Date(ts).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
