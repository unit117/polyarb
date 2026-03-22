import { H1, H2, P, Code, Table, Callout, UL } from "../../components/Prose.tsx";

export default function PositionLimits() {
  return (
    <>
      <H1>Position Limits</H1>

      <P>
        Position limits cap how much capital can be allocated to any single trade or market.
        These limits work alongside Kelly sizing and circuit breakers to prevent over-concentration.
      </P>

      <H2>Limits Overview</H2>

      <Table
        headers={["Limit", "Value", "Scope"]}
        rows={[
          ["Max position size", <Code>$100</Code>, "Per trade leg"],
          ["Max per-market exposure", <Code>$200</Code>, "Total across all positions in one market"],
          ["Initial capital", <Code>$10,000</Code>, "Total portfolio starting value"],
        ]}
      />

      <H2>Per-Trade Limit</H2>

      <P>
        The <Code>max_position_size = 100.0</Code> setting caps any single trade leg
        at $100. This is applied after Kelly sizing — even if Kelly suggests a larger
        position, it's clamped:
      </P>

      <UL>
        <li>Kelly fraction computed from estimated profit</li>
        <li>Drawdown scaling applied</li>
        <li>Result multiplied by <Code>max_position_size</Code></li>
        <li>Each trade leg sized independently</li>
      </UL>

      <H2>Per-Market Limit</H2>

      <P>
        The circuit breaker enforces a <Code>$200</Code> per-market exposure limit. This
        is checked pre-trade by computing what the total position would be after the
        proposed trade. If it would exceed $200 in any single market, the trade is blocked.
      </P>

      <P>
        This prevents a scenario where multiple arbitrage opportunities involving the same
        market could compound into a large concentrated position.
      </P>

      <H2>Cash Check</H2>

      <P>
        Before execution, the simulator verifies that the portfolio has enough cash for all
        legs of the trade. For a buy:
      </P>

      <UL>
        <li><Code>cost = size * vwap_price + fees</Code></li>
        <li>If <Code>cost {">"} available_cash</Code>, the size is reduced to fit</li>
        <li>For multi-leg trades, cash is reserved for all legs before any execute</li>
      </UL>

      <Callout type="info">
        Position limits are intentionally conservative for paper trading. They're designed
        to produce realistic results that would translate to live trading, where venue-level
        position limits may also apply.
      </Callout>
    </>
  );
}
