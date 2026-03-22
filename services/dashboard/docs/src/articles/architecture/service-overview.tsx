import { H1, H2, P, Code, Table, Diagram, Callout, UL } from "../../components/Prose.tsx";

export default function ServiceOverview() {
  return (
    <>
      <H1>Service Overview</H1>

      <P>
        PolyArb runs as seven Docker containers orchestrated with Docker Compose. Each service
        is a single-purpose Python async application that communicates via Redis pub/sub and
        PostgreSQL.
      </P>

      <H2>Container Architecture</H2>

      <Diagram>{`┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│ Ingestor │ │ Detector │ │Optimizer │ │Simulator │ │Dashboard │
│  (async) │ │  (async) │ │  (async) │ │  (async) │ │(FastAPI) │
└────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘
     │             │             │             │             │
     └─────────────┴─────────────┴─────────────┴─────────────┘
                           │                │
                    ┌──────┴──────┐  ┌──────┴──────┐
                    │    Redis    │  │  PostgreSQL  │
                    │  (pub/sub)  │  │  (pgvector)  │
                    └─────────────┘  └─────────────┘`}</Diagram>

      <H2>Services</H2>

      <Table
        headers={["Service", "Role", "Interval"]}
        rows={[
          ["Ingestor", "Fetches markets and price snapshots from venue APIs", "60s"],
          ["Detector", "Discovers market pairs and detects arbitrage opportunities", "60s"],
          ["Optimizer", "Runs Frank-Wolfe optimization on detected opportunities", "30s"],
          ["Simulator", "Executes paper/live trades with VWAP pricing", "60s"],
          ["Dashboard", "FastAPI + React web UI with WebSocket streaming", "Always on"],
          ["PostgreSQL", "Database with pgvector for embeddings", "Always on"],
          ["Redis", "Event bus (pub/sub) and kill switch", "Always on"],
        ]}
      />

      <H2>Service Entry Pattern</H2>

      <P>
        Each Python service follows the same startup pattern in <Code>main.py</Code>:
      </P>

      <UL>
        <li>Configure logging via <Code>setup_logging()</Code></li>
        <li>Initialize database connection via <Code>init_db()</Code></li>
        <li>Create Redis connection</li>
        <li>Instantiate the pipeline (DetectionPipeline, OptimizerPipeline, etc.)</li>
        <li>Run <Code>asyncio.gather()</Code> with periodic loop + event listener</li>
      </UL>

      <H2>Shared Code</H2>

      <P>
        The <Code>shared/</Code> directory contains code imported by all services:
      </P>

      <Table
        headers={["Module", "Purpose"]}
        rows={[
          [<Code>shared/config.py</Code>, "Pydantic settings (all 52+ environment variables)"],
          [<Code>shared/db.py</Code>, "SQLAlchemy async engine and session factory"],
          [<Code>shared/models.py</Code>, "Database models (Market, PriceSnapshot, MarketPair, etc.)"],
          [<Code>shared/events.py</Code>, "Redis channel names, publish/subscribe helpers"],
          [<Code>shared/logging.py</Code>, "Structlog configuration"],
          [<Code>shared/circuit_breaker.py</Code>, "Circuit breaker implementation"],
        ]}
      />

      <Callout type="info">
        Services communicate exclusively via Redis pub/sub — they never import each other's code
        directly. Only <Code>shared/</Code> is imported across service boundaries.
      </Callout>

      <H2>Port Mapping</H2>

      <Table
        headers={["Service", "Container Port", "Host Port"]}
        rows={[
          ["PostgreSQL", "5432", "5434"],
          ["Redis", "6379", "6380"],
          ["Dashboard", "8080", "8081"],
        ]}
      />

      <P>
        Ports 5432, 5433, 6379, and 8080 are already in use on the NAS, which is why PolyArb
        uses different host ports.
      </P>
    </>
  );
}
