import { H1, H2, P, Code, Table, Callout } from "../../components/Prose.tsx";

export default function DatabaseSchema() {
  return (
    <>
      <H1>Database Schema</H1>

      <P>
        PolyArb uses PostgreSQL with the pgvector extension. The schema is managed via Alembic
        migrations (5 revisions). Here are the core tables.
      </P>

      <H2>markets</H2>

      <P>Stores all tracked prediction markets from all venues.</P>

      <Table
        headers={["Column", "Type", "Notes"]}
        rows={[
          [<Code>id</Code>, "SERIAL PK", "Auto-incrementing"],
          [<Code>polymarket_id</Code>, "TEXT", "Venue-specific market ID (indexed)"],
          [<Code>venue</Code>, "TEXT", "\"polymarket\" or \"kalshi\""],
          [<Code>event_id</Code>, "TEXT", "Venue event grouping ID"],
          [<Code>question</Code>, "TEXT", "Market question text"],
          [<Code>description</Code>, "TEXT", "Extended description"],
          [<Code>outcomes</Code>, "JSONB", "Available outcomes and token IDs"],
          [<Code>token_ids</Code>, "JSONB", "CLOB token identifiers"],
          [<Code>active</Code>, "BOOLEAN", "Whether market is still open"],
          [<Code>volume</Code>, "DECIMAL", "Total trading volume"],
          [<Code>liquidity</Code>, "DECIMAL", "Current liquidity"],
          [<Code>embedding</Code>, "Vector(384)", "pgvector embedding for similarity search"],
          [<Code>resolved_outcome</Code>, "TEXT", "Winning outcome after settlement"],
          [<Code>resolved_at</Code>, "TIMESTAMP", "When the market resolved"],
        ]}
      />

      <H2>price_snapshots</H2>

      <P>Time-series price data for each market, captured every ~60 seconds.</P>

      <Table
        headers={["Column", "Type", "Notes"]}
        rows={[
          [<Code>id</Code>, "BIGINT PK", "High-volume table"],
          [<Code>market_id</Code>, "INT FK", "References markets"],
          [<Code>timestamp</Code>, "TIMESTAMP", "When snapshot was taken"],
          [<Code>prices</Code>, "JSONB", "{outcome: price, ...}"],
          [<Code>order_book</Code>, "JSONB", "{bids: [[p, s], ...], asks: [...]}"],
          [<Code>midpoints</Code>, "JSONB", "{outcome: midpoint, ...}"],
        ]}
      />

      <H2>market_pairs</H2>

      <P>Discovered relationships between logically related markets.</P>

      <Table
        headers={["Column", "Type", "Notes"]}
        rows={[
          [<Code>id</Code>, "SERIAL PK", ""],
          [<Code>market_a_id</Code>, "INT FK", "First market"],
          [<Code>market_b_id</Code>, "INT FK", "Second market"],
          [<Code>dependency_type</Code>, "TEXT", "cross_platform, conditional, correlated, binary_complement"],
          [<Code>confidence</Code>, "FLOAT", "LLM classification confidence (0-1)"],
          [<Code>constraint_matrix</Code>, "JSONB", "Feasibility matrix + metadata"],
          [<Code>verified</Code>, "BOOLEAN", "Manual verification status"],
          [<Code>detected_at</Code>, "TIMESTAMP", "When pair was discovered"],
        ]}
      />

      <H2>arbitrage_opportunities</H2>

      <P>Each detected profit opportunity with optimization results.</P>

      <Table
        headers={["Column", "Type", "Notes"]}
        rows={[
          [<Code>id</Code>, "SERIAL PK", ""],
          [<Code>pair_id</Code>, "INT FK", "References market_pairs"],
          [<Code>timestamp</Code>, "TIMESTAMP", "When detected"],
          [<Code>type</Code>, "TEXT", "\"rebalancing\""],
          [<Code>theoretical_profit</Code>, "DECIMAL", "Profit from constraint violation"],
          [<Code>estimated_profit</Code>, "DECIMAL", "After fees/slippage (from optimizer)"],
          [<Code>optimal_trades</Code>, "JSONB", "Trade instructions from optimizer"],
          [<Code>fw_iterations</Code>, "INT", "Frank-Wolfe iterations used"],
          [<Code>bregman_gap</Code>, "FLOAT", "Final duality gap"],
          [<Code>status</Code>, "TEXT", "detected/optimized/unconverged/pending/executed/expired"],
          [<Code>pending_at</Code>, "TIMESTAMP", "When execution started"],
          [<Code>expired_at</Code>, "TIMESTAMP", "When profit disappeared"],
          [<Code>dependency_type</Code>, "TEXT", "Copied from pair for quick access"],
        ]}
      />

      <H2>paper_trades</H2>

      <P>Individual trade leg executions (paper or live).</P>

      <Table
        headers={["Column", "Type", "Notes"]}
        rows={[
          [<Code>id</Code>, "SERIAL PK", ""],
          [<Code>opportunity_id</Code>, "INT FK", "Which opportunity triggered this trade"],
          [<Code>market_id</Code>, "INT FK", "Which market was traded"],
          [<Code>outcome</Code>, "TEXT", "Yes/No or specific outcome"],
          [<Code>side</Code>, "TEXT", "BUY or SELL"],
          [<Code>size</Code>, "DECIMAL", "Number of contracts"],
          [<Code>entry_price</Code>, "DECIMAL", "Price from optimization"],
          [<Code>vwap_price</Code>, "DECIMAL", "Actual fill price (VWAP)"],
          [<Code>slippage</Code>, "DECIMAL", "Execution slippage"],
          [<Code>fees</Code>, "DECIMAL", "Venue fees paid"],
          [<Code>executed_at</Code>, "TIMESTAMP", "When trade was filled"],
          [<Code>status</Code>, "TEXT", "\"filled\""],
          [<Code>source</Code>, "TEXT", "\"paper\" or \"live\""],
          [<Code>venue</Code>, "TEXT", "\"polymarket\" or \"kalshi\""],
        ]}
      />

      <H2>portfolio_snapshots</H2>

      <P>Periodic snapshots of portfolio state for historical tracking.</P>

      <Table
        headers={["Column", "Type", "Notes"]}
        rows={[
          [<Code>id</Code>, "SERIAL PK", ""],
          [<Code>timestamp</Code>, "TIMESTAMP", "When snapshot was taken"],
          [<Code>cash</Code>, "DECIMAL", "Available cash"],
          [<Code>positions</Code>, "JSONB", "All open positions"],
          [<Code>total_value</Code>, "DECIMAL", "Cash + position value"],
          [<Code>realized_pnl</Code>, "DECIMAL", "Cumulative realized PnL"],
          [<Code>unrealized_pnl</Code>, "DECIMAL", "Mark-to-market PnL"],
          [<Code>total_trades</Code>, "INT", "Trade count"],
          [<Code>settled_trades</Code>, "INT", "Settled position count"],
          [<Code>winning_trades</Code>, "INT", "Profitable trade count"],
          [<Code>source</Code>, "TEXT", "\"paper\" or \"live\""],
        ]}
      />

      <Callout type="info">
        All database access is async via SQLAlchemy + asyncpg. Migrations are applied
        automatically on service startup via Alembic.
      </Callout>
    </>
  );
}
