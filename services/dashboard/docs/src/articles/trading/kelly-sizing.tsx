import { H1, H2, P, Code, CodeBlock, Table, Callout, UL } from "../../components/Prose.tsx";

export default function KellySizing() {
  return (
    <>
      <H1>Kelly Criterion Sizing</H1>

      <P>
        PolyArb uses a half-Kelly position sizing strategy to determine how much capital to
        allocate to each arbitrage opportunity. The Kelly criterion maximizes long-term growth
        rate while the half-Kelly variant reduces variance at the cost of slightly lower returns.
      </P>

      <H2>The Formula</H2>

      <P>
        For each opportunity, the base position size is:
      </P>

      <CodeBlock lang="python">{`# Half-Kelly sizing
net_profit = opportunity.optimal_trades["estimated_profit"]
kelly_fraction = min(net_profit * 0.5, 1.0)
base_size = kelly_fraction * max_position_size  # max_position_size = 100`}</CodeBlock>

      <P>
        The <Code>net_profit</Code> is the estimated profit after fees and slippage from the
        Frank-Wolfe optimizer. The half-Kelly fraction is capped at 1.0 (never more than
        the full position limit).
      </P>

      <H2>Drawdown Scaling</H2>

      <P>
        When the portfolio is in drawdown, position sizes are automatically reduced to protect
        capital:
      </P>

      <Table
        headers={["Drawdown", "Scale Factor", "Effect"]}
        rows={[
          ["0-5%", "100%", "Full position size"],
          ["5-10%", "100% → 50%", "Linear reduction"],
          ["10%+", "50%", "Minimum position size"],
        ]}
      />

      <CodeBlock lang="python">{`# Drawdown scaling
drawdown = (initial_capital - total_value) / initial_capital

if drawdown > 0.05:
    drawdown_scale = max(0.5, 1.0 - (drawdown - 0.05) / 0.10)
    kelly_fraction *= drawdown_scale`}</CodeBlock>

      <P>
        At 5% drawdown, sizing is unchanged. At 7.5% drawdown, it's reduced by 25%.
        At 10%+ drawdown, it's halved. This prevents aggressive betting during losing streaks.
      </P>

      <H2>Why Half-Kelly?</H2>

      <UL>
        <li><strong>Full Kelly</strong> maximizes growth but has extreme variance — a bad streak can wipe out gains</li>
        <li><strong>Half-Kelly</strong> achieves 75% of the growth rate with significantly less variance</li>
        <li>Prediction market price estimates have uncertainty — half-Kelly provides a safety margin</li>
        <li>Combined with drawdown scaling, this creates an adaptive sizing strategy</li>
      </UL>

      <Callout type="info">
        The max position size is <Code>$100</Code> per trade leg (<Code>max_position_size = 100.0</Code>).
        This is a hard cap independent of Kelly sizing — even if Kelly suggests a larger position,
        it's clamped to this limit.
      </Callout>
    </>
  );
}
