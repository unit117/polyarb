import s from "./CostWaterfall.module.css";

interface Props {
  theoretical: number;
  estimated: number; // net edge after fees + slippage
  gate?: number; // simulator min net edge
}

// Simulator's min_net_profit (shared/config.py). Hardcoded until a /config
// endpoint exposes it; the gate is illustrative — every shown opp already
// cleared the optimizer's edge filter.
const DEFAULT_GATE = 0.005;

/**
 * Where the edge goes: theoretical arb edge, minus fees + slippage, to net.
 * The single most informative number in the system — it shows why prediction-
 * market arb is thin. Inputs are per-share edge in price units (0–1).
 */
export default function CostWaterfall({ theoretical, estimated, gate = DEFAULT_GATE }: Props) {
  const cost = theoretical - estimated;
  const ref = Math.max(theoretical, estimated, 1e-9);
  const netPct = clamp((estimated / ref) * 100);
  const costPct = clamp((cost / ref) * 100);
  const gatePct = clamp((gate / ref) * 100);
  const passesGate = estimated >= gate;
  const survival = theoretical > 0 ? (estimated / theoretical) * 100 : 0;

  return (
    <div className={s.wrap}>
      <div className={s.track}>
        <div className={s.net} style={{ width: `${netPct}%` }} />
        <div className={s.cost} style={{ width: `${costPct}%` }} />
        <div className={s.gate} style={{ left: `${gatePct}%` }} />
      </div>

      <div className={s.legend}>
        <Item label="Theoretical" value={fmt(theoretical)} color="var(--color-blue)" />
        <Item label="− Fees & slip" value={fmt(-cost)} color="var(--color-red)" />
        <Item
          label="Net edge"
          value={fmt(estimated)}
          color={passesGate ? "var(--color-green)" : "var(--color-yellow)"}
          sub={theoretical > 0 ? `${survival.toFixed(0)}% kept` : undefined}
        />
      </div>

      <div className={s.caption}>
        <span className={s.gateMark} />
        min net {fmt(gate)} · {passesGate ? "clears gate" : "below gate"}
      </div>
    </div>
  );
}

function Item({
  label,
  value,
  color,
  sub,
}: {
  label: string;
  value: string;
  color: string;
  sub?: string;
}) {
  return (
    <div className={s.item}>
      <div className={s.itemLabel}>{label}</div>
      <div className={s.itemValue} style={{ color }}>
        {value}
      </div>
      {sub && <div className={s.itemSub}>{sub}</div>}
    </div>
  );
}

function clamp(n: number): number {
  return Math.max(0, Math.min(100, n));
}
function fmt(v: number): string {
  return `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(4)}`;
}
