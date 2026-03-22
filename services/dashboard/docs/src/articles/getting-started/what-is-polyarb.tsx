import { H1, H2, P, Code, Diagram, Callout, DashboardLink, UL } from "../../components/Prose.tsx";

export default function WhatIsPolyArb() {
  return (
    <>
      <H1>What is PolyArb?</H1>

      <P>
        PolyArb is a combinatorial arbitrage detection and paper-trading system for prediction markets.
        It continuously monitors markets on venues like Polymarket and Kalshi, identifies mathematically
        provable arbitrage opportunities across correlated markets, and executes paper trades to capture
        risk-free profit.
      </P>

      <H2>The Core Idea</H2>

      <P>
        Prediction markets let you buy and sell contracts on the outcomes of real-world events. When two
        or more markets are logically related (e.g., "Will the Fed raise rates in June?" and "Will the
        Fed raise rates in 2024?"), their prices should be mathematically consistent. When they're not,
        that's an arbitrage opportunity — a guaranteed profit regardless of which outcome occurs.
      </P>

      <P>
        PolyArb finds these inconsistencies automatically using embedding similarity to discover related
        markets, then uses Frank-Wolfe optimization to compute the optimal portfolio that captures the
        spread.
      </P>

      <H2>How It Works</H2>

      <Diagram>{`Ingestor → Detector → Optimizer → Simulator → Dashboard
   ↓          ↓          ↓           ↓          ↓
Markets    Pairs    Opportunities  Portfolio   Web UI
         (pgvector)  (Frank-Wolfe)  (VWAP)   (React+WS)
                         ↕
              Redis Event Bus (8 channels)
                         ↕
                    PostgreSQL (pgvector)`}</Diagram>

      <UL>
        <li><strong>Ingestor</strong> — fetches live market data and price snapshots from venue APIs</li>
        <li><strong>Detector</strong> — discovers correlated market pairs using embeddings and validates dependencies</li>
        <li><strong>Optimizer</strong> — runs Frank-Wolfe optimization to find profitable arbitrage portfolios</li>
        <li><strong>Simulator</strong> — executes paper trades with realistic VWAP pricing, fees, and slippage</li>
        <li><strong>Dashboard</strong> — real-time web UI with WebSocket streaming</li>
      </UL>

      <H2>Key Features</H2>

      <UL>
        <li>Automatic discovery of correlated markets using OpenAI embeddings + pgvector</li>
        <li>Four dependency types: mutual exclusion, partition, conditional, implication</li>
        <li>Frank-Wolfe optimization (Dudik, Lahaie & Pennock 2016) for optimal portfolio sizing</li>
        <li>Realistic paper trading with VWAP execution, orderbook slippage, and fee modeling</li>
        <li>Circuit breakers, Kelly criterion sizing, and freshness bounds for safety</li>
        <li>Multi-venue support (Polymarket + Kalshi)</li>
        <li>Real-time dashboard with WebSocket streaming</li>
      </UL>

      <Callout type="tip">
        Start by exploring the <DashboardLink tab="opportunities">Opportunities table</DashboardLink> to
        see live arbitrage opportunities as they're detected.
      </Callout>

      <H2>Tech Stack</H2>

      <UL>
        <li><strong>Backend:</strong> Python 3.12, asyncio, FastAPI, SQLAlchemy async, asyncpg</li>
        <li><strong>Database:</strong> PostgreSQL with pgvector extension</li>
        <li><strong>Messaging:</strong> Redis pub/sub</li>
        <li><strong>Frontend:</strong> React 19, TypeScript, Vite, Recharts</li>
        <li><strong>Infrastructure:</strong> Docker Compose (7 containers), deployed on Synology NAS</li>
        <li><strong>AI:</strong> OpenAI embeddings (text-embedding-3-small, 384 dimensions)</li>
      </UL>

      <P>
        The system runs 24/7 on a NAS at <Code>$NAS_HOST</Code>, with the dashboard
        accessible at port <Code>8081</Code>.
      </P>
    </>
  );
}
