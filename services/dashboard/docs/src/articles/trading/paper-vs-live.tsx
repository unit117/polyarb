import { H1, H2, P, Code, Table, Callout, UL } from "../../components/Prose.tsx";

export default function PaperVsLive() {
  return (
    <>
      <H1>Paper vs Live Trading</H1>

      <P>
        PolyArb supports two trading modes: paper trading (simulated) and live trading (real money).
        Both use the same detection and optimization pipeline — only the execution differs.
      </P>

      <H2>Paper Trading</H2>

      <P>
        Paper trading simulates trades using real market data but without placing actual orders.
        The simulator:
      </P>

      <UL>
        <li>Uses real orderbook data to compute VWAP fill prices</li>
        <li>Models realistic slippage based on orderbook depth</li>
        <li>Applies venue-specific fee calculations</li>
        <li>Tracks a virtual portfolio with cash, positions, and PnL</li>
        <li>Settles positions when markets resolve</li>
      </UL>

      <P>
        Paper trades are stored in the <Code>paper_trades</Code> table with <Code>source = "paper"</Code>.
        Portfolio snapshots are taken periodically for historical tracking.
      </P>

      <H2>Live Trading</H2>

      <P>
        Live trading places real orders on venue APIs. It uses the same pipeline but with additional
        safety checks:
      </P>

      <UL>
        <li>All circuit breakers must pass before each trade</li>
        <li>Kill switch checked in Redis before every execution</li>
        <li>Separate portfolio tracking (<Code>source = "live"</Code>)</li>
        <li>Dry-run writes audit intent only; real live ledger rows are fill-driven</li>
        <li>Live trading is disabled by default and must be explicitly enabled</li>
      </UL>

      <Callout type="warning">
        Live trading is a separate system that requires explicit enablement. The paper trading
        simulator does not interact with venue APIs — it only uses price data for simulation.
      </Callout>

      <H2>Mode Switching</H2>

      <P>
        The dashboard header has a Paper/Live toggle that switches which data you're viewing.
        Both modes run independently — paper trading continues even when live trading is active.
      </P>

      <H2>Live Audit Trail</H2>

      <P>
        Live trading now has three separate layers of records:
      </P>

      <UL>
        <li><Code>live_orders</Code> for intent and order lifecycle</li>
        <li><Code>live_fills</Code> for reconciled venue-confirmed fills</li>
        <li><Code>paper_trades(source = "live")</Code> for dashboard-facing live ledger rows derived only from confirmed fills and settlements</li>
      </UL>

      <P>
        In dry-run mode, only <Code>live_orders</Code> rows are written with <Code>status = "dry_run"</Code>.
        No fake live fills or live ledger trades are created.
      </P>

      <Table
        headers={["Feature", "Paper", "Live"]}
        rows={[
          ["Execution", "Simulated (VWAP model)", "Real orders via API"],
          ["Risk", "None — virtual money", "Real capital at risk"],
          ["Fees", "Modeled accurately", "Actual venue fees"],
          ["Slippage", "VWAP estimate from orderbook", "Actual execution slippage"],
          ["Portfolio tracking", "paper_trades with source=paper", "live_orders + live_fills + paper_trades with source=live"],
          ["Circuit breakers", "Applied", "Applied (stricter)"],
          ["Default state", "Always active", "Disabled by default"],
        ]}
      />

      <H2>Initial Capital</H2>

      <P>
        Paper trading starts with <Code>$10,000</Code> in virtual capital
        (<Code>initial_capital = 10000.0</Code>). This can be configured
        via the <Code>INITIAL_CAPITAL</Code> environment variable.
      </P>
    </>
  );
}
