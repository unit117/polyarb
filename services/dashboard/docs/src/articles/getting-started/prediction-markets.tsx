import { H1, H2, H3, P, Code, Table, Callout, Term, UL } from "../../components/Prose.tsx";

export default function PredictionMarkets() {
  return (
    <>
      <H1>How Prediction Markets Work</H1>

      <P>
        Prediction markets are exchanges where you can buy and sell contracts on the outcomes of
        real-world events. Each contract pays out a fixed amount (typically $1) if a specific outcome
        occurs, and $0 if it doesn't. The market price reflects the crowd's estimated probability
        of that outcome.
      </P>

      <H2>Binary Markets</H2>

      <P>
        The simplest prediction market is a binary market with two outcomes: Yes and No.
        If "Yes" is trading at $0.65 and "No" at $0.35, the market collectively estimates a 65%
        probability of the event occurring.
      </P>

      <Table
        headers={["Contract", "Price", "Payout if True", "Payout if False"]}
        rows={[
          ["Yes", "$0.65", "$1.00", "$0.00"],
          ["No", "$0.35", "$1.00", "$0.00"],
        ]}
      />

      <Callout type="info">
        In an efficient binary market, Yes + No prices should sum to $1.00. When they don't, there's
        an opportunity.
      </Callout>

      <H2>Multi-Outcome Markets</H2>

      <P>
        Many markets have more than two outcomes. For example, "Who will win the election?" might
        have contracts for each candidate. In a well-priced market, all outcome prices should sum
        to $1.00 (since exactly one outcome will occur).
      </P>

      <H2>The CLOB Model</H2>

      <P>
        Polymarket uses a <Term term="CLOB" definition="Central Limit Order Book — a matching engine where buyers and sellers place limit orders at specific prices" /> model.
        Traders place limit orders specifying the price and quantity they're willing to trade.
        The exchange matches buy and sell orders automatically.
      </P>

      <H3>Orderbook Depth</H3>

      <P>
        The orderbook shows all outstanding buy and sell orders at each price level. The
        difference between the best buy (bid) and best sell (ask) is the{" "}
        <Term term="spread" definition="The difference between the best bid and best ask price — represents the cost of immediately executing a trade" />.
        Thin orderbooks (few orders) mean higher slippage when executing large trades.
      </P>

      <H2>Why Prices Deviate</H2>

      <P>
        In theory, correlated markets should always be priced consistently. In practice, prices
        diverge because:
      </P>

      <UL>
        <li><strong>Fragmented liquidity</strong> — different traders in different markets</li>
        <li><strong>Information asymmetry</strong> — news reaches markets at different speeds</li>
        <li><strong>Transaction costs</strong> — fees and slippage make small arbitrages unprofitable</li>
        <li><strong>Cross-venue gaps</strong> — Polymarket and Kalshi have independent orderbooks</li>
        <li><strong>Behavioral biases</strong> — markets can overreact or underreact to events</li>
      </UL>

      <P>
        PolyArb exploits these price deviations by continuously monitoring for inconsistencies
        and computing the optimal trades to capture the spread.
      </P>

      <H2>Key Concepts</H2>

      <Table
        headers={["Term", "Definition"]}
        rows={[
          ["Contract", "A tradeable instrument that pays $1 if an outcome occurs"],
          ["Position", "Your holding in a contract (number of shares)"],
          ["Long", "Buying a contract, betting the outcome will occur"],
          ["Short", "Selling a contract, betting the outcome won't occur"],
          ["Settlement", "When a market resolves and contracts pay out"],
          ["Liquidity", "How easily you can buy/sell without moving the price"],
          [<Code>mid price</Code>, "Average of best bid and best ask"],
        ]}
      />
    </>
  );
}
