import { H1, H2, P, Code, CodeBlock, Table, Callout } from "../../components/Prose.tsx";

export default function SlippageFees() {
  return (
    <>
      <H1>Slippage & Fees</H1>

      <P>
        Every trade has two costs beyond the contract price: slippage (price impact from orderbook
        depth) and fees (venue charges). Both are modeled accurately in PolyArb's simulator.
      </P>

      <H2>Slippage Model</H2>

      <P>
        Slippage is the difference between the expected price (midpoint) and the actual execution
        price (VWAP). It's expressed as a percentage:
      </P>

      <CodeBlock lang="text">{`slippage = |vwap_price - midpoint| / midpoint`}</CodeBlock>

      <P>
        Slippage depends on:
      </P>

      <Table
        headers={["Factor", "Effect"]}
        rows={[
          ["Order size", "Larger orders consume more levels → more slippage"],
          ["Orderbook depth", "Thin books have larger gaps between levels"],
          ["Spread width", "Wider bid-ask spread means higher base slippage"],
          ["Market liquidity", "Popular markets have tighter books"],
        ]}
      />

      <P>
        When no orderbook data is available, a fixed estimate of <Code>0.5%</Code> is used.
      </P>

      <H2>Fee Models</H2>

      <P>
        Each venue has a different fee structure. PolyArb models both accurately:
      </P>

      <H2>Polymarket Fees</H2>

      <CodeBlock lang="python">{`def polymarket_fee(price, side):
    return price * (1 - price) * 0.015`}</CodeBlock>

      <P>
        Polymarket charges 1.5% of <Code>price * (1 - price)</Code>. This means fees are highest
        at <Code>price = 0.50</Code> (max fee = 0.375%) and approach zero at extreme prices
        (near 0 or 1). The fee is the same for buys and sells.
      </P>

      <Table
        headers={["Price", "Fee", "Fee %"]}
        rows={[
          ["$0.10", "$0.00135", "1.35%"],
          ["$0.25", "$0.00281", "1.12%"],
          ["$0.50", "$0.00375", "0.75%"],
          ["$0.75", "$0.00281", "0.37%"],
          ["$0.90", "$0.00135", "0.15%"],
        ]}
      />

      <H2>Kalshi Fees</H2>

      <CodeBlock lang="python">{`def kalshi_fee(price):
    return ceil(7.0 * price * (1 - price)) / 100.0`}</CodeBlock>

      <P>
        Kalshi charges 7% of <Code>price * (1 - price)</Code>, rounded up to the nearest cent.
        This is significantly higher than Polymarket, especially at mid-range prices.
      </P>

      <Table
        headers={["Price", "Kalshi Fee", "Polymarket Fee"]}
        rows={[
          ["$0.50", "$0.02", "$0.00375"],
          ["$0.75", "$0.02", "$0.00281"],
          ["$0.90", "$0.01", "$0.00135"],
        ]}
      />

      <Callout type="warning">
        Kalshi's higher fee structure means cross-venue arbitrage between Polymarket and Kalshi
        needs a wider spread to be profitable. The optimizer accounts for venue-specific fees
        when computing estimated profit.
      </Callout>
    </>
  );
}
