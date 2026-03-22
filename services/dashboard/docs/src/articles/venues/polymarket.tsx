import { H1, H2, P, Code, CodeBlock, Table, Callout, UL } from "../../components/Prose.tsx";

export default function Polymarket() {
  return (
    <>
      <H1>Polymarket</H1>

      <P>
        Polymarket is the primary venue for PolyArb. It's a prediction market exchange based on
        the Polygon blockchain that uses a Central Limit Order Book (CLOB) model for trading.
      </P>

      <H2>CLOB API</H2>

      <P>
        PolyArb interacts with Polymarket through the CLOB API, which provides:
      </P>

      <UL>
        <li><strong>Market data</strong> — questions, outcomes, token IDs, event grouping</li>
        <li><strong>Price data</strong> — real-time prices and orderbook snapshots</li>
        <li><strong>Price history</strong> — historical price data for backtesting</li>
      </UL>

      <H2>Market Structure</H2>

      <P>
        Each Polymarket market has:
      </P>

      <Table
        headers={["Field", "Description"]}
        rows={[
          ["condition_id", "Unique market identifier"],
          ["question", "The prediction question"],
          ["outcomes", "Usually [\"Yes\", \"No\"] for binary markets"],
          ["token_ids", "CLOB token identifiers for each outcome"],
          ["end_date", "When the market is expected to resolve"],
          ["volume", "Total trading volume in USD"],
          ["liquidity", "Current available liquidity"],
        ]}
      />

      <H2>Fee Structure</H2>

      <CodeBlock lang="python">{`def polymarket_fee(price, side):
    return price * (1 - price) * 0.015  # 1.5% of p(1-p)`}</CodeBlock>

      <P>
        Fees are lowest at extreme prices (near $0 or $1) and highest at $0.50. This means
        arbitrage on high-conviction markets (prices near 0 or 1) has lower fee drag.
      </P>

      <H2>Orderbook Data</H2>

      <P>
        The CLOB API returns orderbook snapshots as arrays of [price, size] pairs:
      </P>

      <CodeBlock lang="json">{`{
  "bids": [["0.65", "500"], ["0.64", "300"], ["0.63", "200"]],
  "asks": [["0.66", "400"], ["0.67", "250"], ["0.68", "150"]]
}`}</CodeBlock>

      <Callout type="warning">
        Polymarket returns prices as strings in JSONB — always <Code>float()</Code> cast
        when processing. This is a common gotcha that has caused bugs in the past.
      </Callout>

      <H2>Price History Limitation</H2>

      <P>
        The <Code>/prices-history</Code> endpoint rejects requests for intervals longer than
        ~14 days. The backfill script chunks requests into 14-day windows to work around this.
      </P>

      <H2>Resolution</H2>

      <P>
        When a market resolves, the winning outcome pays $1.00 and all others pay $0.00.
        PolyArb detects resolution when an outcome price crosses the <Code>resolution_price_threshold
        = 0.98</Code> threshold, and settles positions accordingly.
      </P>
    </>
  );
}
