import { H1, H2, P, Code, Table, Callout } from "../../components/Prose.tsx";

export default function Configuration() {
  return (
    <>
      <H1>Configuration</H1>

      <P>
        All PolyArb settings are managed via environment variables loaded by pydantic-settings.
        See <Code>.env.example</Code> for the full list of 52+ settings.
      </P>

      <H2>Database</H2>

      <Table
        headers={["Setting", "Default", "Description"]}
        rows={[
          [<Code>POSTGRES_HOST</Code>, "postgres", "Database hostname"],
          [<Code>POSTGRES_PORT</Code>, "5432", "Database port"],
          [<Code>POSTGRES_DB</Code>, "polyarb", "Database name"],
          [<Code>POSTGRES_USER</Code>, "polyarb", "Database user"],
          [<Code>POSTGRES_PASSWORD</Code>, "—", "Database password"],
        ]}
      />

      <H2>Redis</H2>

      <Table
        headers={["Setting", "Default", "Description"]}
        rows={[
          [<Code>REDIS_HOST</Code>, "redis", "Redis hostname"],
          [<Code>REDIS_PORT</Code>, "6379", "Redis port"],
        ]}
      />

      <H2>Detector</H2>

      <Table
        headers={["Setting", "Default", "Description"]}
        rows={[
          [<Code>SIMILARITY_THRESHOLD</Code>, "0.82", "Min cosine similarity for pair candidates"],
          [<Code>SIMILARITY_TOP_K</Code>, "20", "Max similar markets per query"],
          [<Code>DETECTOR_BATCH_SIZE</Code>, "100", "Markets processed per detection cycle"],
          [<Code>CLASSIFIER_MODEL</Code>, "gpt-4.1-mini", "LLM for dependency classification"],
          [<Code>DETECTION_INTERVAL_SECONDS</Code>, "60", "Detection cycle interval"],
        ]}
      />

      <H2>Optimizer</H2>

      <Table
        headers={["Setting", "Default", "Description"]}
        rows={[
          [<Code>FW_MAX_ITERATIONS</Code>, "200", "Max Frank-Wolfe iterations"],
          [<Code>FW_GAP_TOLERANCE</Code>, "0.001", "Convergence threshold (duality gap)"],
          [<Code>FW_IP_TIMEOUT_MS</Code>, "5000", "IP oracle timeout per iteration"],
          [<Code>OPTIMIZER_INTERVAL_SECONDS</Code>, "30", "Optimization cycle interval"],
          [<Code>OPTIMIZER_MIN_EDGE</Code>, "0.03", "Min profit edge to trade"],
          [<Code>OPTIMIZER_SKIP_CONDITIONAL</Code>, "true", "Skip conditional dependency pairs"],
        ]}
      />

      <H2>Simulator</H2>

      <Table
        headers={["Setting", "Default", "Description"]}
        rows={[
          [<Code>INITIAL_CAPITAL</Code>, "10000.0", "Starting paper capital"],
          [<Code>MAX_POSITION_SIZE</Code>, "100.0", "Max per-trade-leg size"],
          [<Code>SLIPPAGE_MODEL</Code>, "vwap", "Slippage calculation method"],
          [<Code>SIMULATOR_INTERVAL_SECONDS</Code>, "60", "Simulation cycle interval"],
          [<Code>MAX_SNAPSHOT_AGE_SECONDS</Code>, "120", "Max price staleness before rejection"],
        ]}
      />

      <H2>Circuit Breakers</H2>

      <Table
        headers={["Setting", "Default", "Description"]}
        rows={[
          [<Code>CB_MAX_DAILY_LOSS</Code>, "500.0", "Max daily loss before halt"],
          [<Code>CB_MAX_POSITION_PER_MARKET</Code>, "200.0", "Max exposure per market"],
          [<Code>CB_MAX_DRAWDOWN_PCT</Code>, "10.0", "Max portfolio drawdown percentage"],
          [<Code>CB_MAX_CONSECUTIVE_ERRORS</Code>, "5", "Max consecutive failures"],
          [<Code>CB_COOLDOWN_SECONDS</Code>, "300", "Cooldown after circuit breaker trip"],
        ]}
      />

      <H2>Settlement</H2>

      <Table
        headers={["Setting", "Default", "Description"]}
        rows={[
          [<Code>RESOLUTION_PRICE_THRESHOLD</Code>, "0.98", "Price above which a market is considered resolved"],
          [<Code>SETTLEMENT_INTERVAL_SECONDS</Code>, "120", "Settlement check interval"],
        ]}
      />

      <H2>Embeddings</H2>

      <Table
        headers={["Setting", "Default", "Description"]}
        rows={[
          [<Code>EMBEDDING_DIMENSIONS</Code>, "384", "Vector dimensions for embeddings"],
          [<Code>EMBEDDING_MODEL</Code>, "text-embedding-3-small", "OpenAI embedding model"],
        ]}
      />

      <Callout type="tip">
        All settings can be overridden by setting the corresponding environment variable
        in <Code>.env</Code> or in <Code>docker-compose.yml</Code>. Settings names are
        case-insensitive.
      </Callout>
    </>
  );
}
