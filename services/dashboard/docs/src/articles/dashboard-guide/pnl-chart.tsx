import { H1, H2, P, Code, Callout, UL } from "../../components/Prose.tsx";

export default function PnlChart() {
  return (
    <>
      <H1>PnL Chart</H1>

      <P>
        The PnL chart shows a 24-hour history of portfolio performance with four series
        plotted together.
      </P>

      <H2>Chart Series</H2>

      <UL>
        <li><strong style={{ color: "var(--color-green)" }}>Total Value</strong> — cash + all position values at current market prices</li>
        <li><strong style={{ color: "var(--color-blue)" }}>Cash</strong> — available cash balance</li>
        <li><strong style={{ color: "var(--color-yellow)" }}>Realized PnL</strong> — cumulative profit/loss from settled trades</li>
        <li><strong style={{ color: "var(--color-orange)" }}>Unrealized PnL</strong> — paper profit/loss on open positions</li>
      </UL>

      <H2>Reading the Chart</H2>

      <P>
        <strong>Cash drops when you buy</strong> — a dip in the cash line means the simulator
        executed a trade. The total value should remain stable (cash was converted to positions).
      </P>

      <P>
        <strong>Realized PnL is monotonic (ish)</strong> — it only changes when positions settle
        or are closed. Each step up or down represents a completed trade.
      </P>

      <P>
        <strong>Unrealized PnL fluctuates</strong> — it reflects current market prices for open
        positions. It can swing positive or negative as markets move.
      </P>

      <P>
        <strong>Total value = Cash + Unrealized</strong> — the total value line should always
        equal cash plus the sum of all open position values.
      </P>

      <H2>Data Source</H2>

      <P>
        The chart data comes from the <Code>/portfolio/history</Code> API endpoint, which returns
        hourly portfolio snapshots from the <Code>portfolio_snapshots</Code> table. Snapshots are
        filtered by the current mode (paper or live).
      </P>

      <Callout type="info">
        The chart is built with Recharts and updates in real-time. When a new trade executes,
        the WebSocket triggers a refetch of the portfolio history, and the chart smoothly
        animates to include the new data point.
      </Callout>
    </>
  );
}
