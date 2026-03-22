import { H1, H2, P, Code, CodeBlock, Table, Callout, UL } from "../../components/Prose.tsx";

export default function Kalshi() {
  return (
    <>
      <H1>Kalshi</H1>

      <P>
        Kalshi is a CFTC-regulated prediction market exchange in the US. PolyArb integrates
        with Kalshi as a second venue, enabling cross-platform arbitrage between Polymarket
        and Kalshi.
      </P>

      <H2>RSA-SHA256 Authentication</H2>

      <P>
        Unlike Polymarket's simpler API key authentication, Kalshi uses RSA-SHA256 signed
        requests. Each API call must include a signature computed from:
      </P>

      <UL>
        <li>The request timestamp</li>
        <li>The HTTP method</li>
        <li>The request path</li>
        <li>Your RSA private key</li>
      </UL>

      <P>
        This provides stronger authentication but adds complexity to the API client.
      </P>

      <H2>Fee Structure</H2>

      <CodeBlock lang="python">{`def kalshi_fee(price):
    return ceil(7.0 * price * (1 - price)) / 100.0`}</CodeBlock>

      <P>
        Kalshi charges 7% of <Code>price * (1 - price)</Code>, rounded up to the nearest cent.
        This is roughly 4.7x higher than Polymarket's fee at mid-range prices.
      </P>

      <Table
        headers={["Price", "Kalshi Fee", "Polymarket Fee", "Ratio"]}
        rows={[
          ["$0.50", "$0.02", "$0.00375", "5.3x"],
          ["$0.75", "$0.02", "$0.00281", "7.1x"],
          ["$0.90", "$0.01", "$0.00135", "7.4x"],
        ]}
      />

      <Callout type="warning">
        Kalshi's higher fees mean cross-venue arbitrage needs wider spreads to be profitable.
        The optimizer factors in venue-specific fees when computing estimated profit.
      </Callout>

      <H2>Cross-Platform Detection</H2>

      <P>
        The detector identifies cross-platform pairs by:
      </P>

      <UL>
        <li>Matching Polymarket and Kalshi markets by embedding similarity</li>
        <li>Auto-classifying pairs with similarity ≥ 0.92 as <Code>cross_platform</Code></li>
        <li>Using LLM classification for pairs between 0.82 and 0.92 similarity</li>
      </UL>

      <H2>Venue Column</H2>

      <P>
        The <Code>markets</Code> table has a <Code>venue</Code> column that distinguishes
        between Polymarket and Kalshi markets. The <Code>paper_trades</Code> table also tracks
        which venue each trade was executed on.
      </P>

      <Table
        headers={["Venue", "Market ID Field", "Token Format"]}
        rows={[
          ["polymarket", <Code>polymarket_id</Code>, "CLOB token IDs"],
          ["kalshi", <Code>polymarket_id</Code>, "Kalshi ticker symbol"],
        ]}
      />

      <P>
        Both venues share the <Code>polymarket_id</Code> column (historical naming), but Kalshi
        markets use the Kalshi ticker as their identifier.
      </P>
    </>
  );
}
