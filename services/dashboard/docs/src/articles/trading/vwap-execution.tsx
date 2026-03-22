import { H1, H2, H3, P, Code, CodeBlock, Table, Callout, UL } from "../../components/Prose.tsx";

export default function VwapExecution() {
  return (
    <>
      <H1>VWAP Execution</H1>

      <P>
        VWAP (Volume-Weighted Average Price) is the execution model PolyArb uses to estimate
        realistic fill prices. Instead of assuming you can trade at the mid price, VWAP walks
        through the orderbook to compute the actual average price you'd pay for a given size.
      </P>

      <H2>How It Works</H2>

      <P>
        When executing a buy order, the algorithm walks up the ask side of the orderbook,
        filling at each price level until the full order size is met. For sells, it walks
        down the bid side.
      </P>

      <CodeBlock lang="python">{`# Simplified VWAP walk
levels = order_book["asks"]  # for BUY
total_cost = 0
remaining = order_size

for price, available in levels:
    fill = min(remaining, available)
    total_cost += fill * price
    remaining -= fill
    if remaining <= 0:
        break

vwap_price = total_cost / order_size`}</CodeBlock>

      <H2>Output</H2>

      <P>
        The VWAP computation returns:
      </P>

      <Table
        headers={["Field", "Description"]}
        rows={[
          [<Code>vwap_price</Code>, "Actual fill price (rounded to 6 decimals)"],
          [<Code>slippage</Code>, "|vwap_price - midpoint| / midpoint"],
          [<Code>filled_size</Code>, "Actual size filled (may be less if liquidity is thin)"],
          [<Code>levels_consumed</Code>, "Number of orderbook levels touched"],
          [<Code>partial_fill</Code>, "True if orderbook didn't have enough liquidity"],
        ]}
      />

      <H2>Fallback: No Orderbook</H2>

      <P>
        When orderbook data is unavailable, PolyArb uses a fixed slippage estimate
        of <Code>0.5%</Code>:
      </P>

      <UL>
        <li>Buy: <Code>vwap_price = midpoint * 1.005</Code></li>
        <li>Sell: <Code>vwap_price = midpoint * 0.995</Code></li>
      </UL>

      <H3>Post-VWAP Edge Check</H3>

      <P>
        After computing the VWAP price, the simulator validates that the trade is still
        profitable. Specifically, it checks:
      </P>

      <CodeBlock lang="text">{`(fair_price - vwap_price) - fee > 0`}</CodeBlock>

      <P>
        If the edge disappears after accounting for the actual fill price and fees, the
        trade leg is rejected and the opportunity reverts to "optimized" status for
        re-evaluation.
      </P>

      <Callout type="tip">
        The VWAP model is critical for accurate paper trading. It prevents the common backtesting
        trap of assuming infinite liquidity at the mid price, which would grossly overstate
        profitability.
      </Callout>
    </>
  );
}
