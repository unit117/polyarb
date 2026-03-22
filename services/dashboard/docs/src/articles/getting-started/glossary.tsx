import { H1, P, Table } from "../../components/Prose.tsx";

export default function Glossary() {
  return (
    <>
      <H1>Glossary</H1>

      <P>
        Key terms used throughout PolyArb and prediction market trading.
      </P>

      <Table
        headers={["Term", "Definition"]}
        rows={[
          ["Arbitrage", "Simultaneous trades across related markets to capture a risk-free profit from price inconsistencies"],
          ["Ask", "The lowest price a seller is willing to accept for a contract"],
          ["Bid", "The highest price a buyer is willing to pay for a contract"],
          ["Binary market", "A market with exactly two outcomes: Yes and No"],
          ["Bregman gap", "Convergence metric for Frank-Wolfe optimization — smaller means closer to optimal"],
          ["Circuit breaker", "Safety mechanism that halts trading when risk thresholds are exceeded"],
          ["CLOB", "Central Limit Order Book — exchange model where buyers and sellers place limit orders"],
          ["Conditional dependency", "Relationship where one event implies another (P(A) ≤ P(B))"],
          ["Cost basis", "The total cost of acquiring a position, used to calculate profit/loss"],
          ["Deduplication", "Preventing the same arbitrage opportunity from being traded multiple times"],
          ["Embedding", "A vector representation of text (market question) used to find semantically similar markets"],
          ["Frank-Wolfe", "Optimization algorithm used to find optimal arbitrage portfolios under constraints"],
          ["Freshness bound", "Maximum age of price data before it's considered stale and rejected"],
          ["Implication", "A dependency type where outcome A logically implies outcome B"],
          ["Kelly criterion", "Position sizing formula that maximizes long-term growth rate of capital"],
          ["Liquidity", "How easily a contract can be bought/sold without significantly affecting its price"],
          ["Mid price", "Average of the best bid and best ask: (bid + ask) / 2"],
          ["Mutual exclusion", "A dependency where two outcomes cannot both be true (P(A) + P(B) ≤ 1)"],
          ["Orderbook", "The list of all outstanding buy and sell orders for a contract at each price level"],
          ["Paper trading", "Simulated trading using real market data but without risking real money"],
          ["Partition", "A dependency where outcomes are exhaustive and exclusive (probabilities sum to 1)"],
          ["pgvector", "PostgreSQL extension for storing and querying vector embeddings efficiently"],
          ["PnL", "Profit and Loss — the financial result of trading activity"],
          ["Position", "The number of shares held in a particular contract"],
          ["Realized PnL", "Profit/loss from trades that have been closed (settled or exited)"],
          ["Settlement", "When a market resolves and contracts pay out based on the real-world outcome"],
          ["Slippage", "The difference between expected price and actual execution price due to orderbook depth"],
          ["Spread", "The difference between the best bid and best ask price"],
          ["Unrealized PnL", "Profit/loss on positions that are still open, based on current market prices"],
          ["VWAP", "Volume-Weighted Average Price — execution price that accounts for orderbook depth"],
          ["WebSocket", "Real-time communication protocol used by the dashboard for live updates"],
        ]}
      />
    </>
  );
}
