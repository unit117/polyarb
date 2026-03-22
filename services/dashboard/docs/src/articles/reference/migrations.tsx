import { H1, H2, P, Code, CodeBlock, Table, Callout } from "../../components/Prose.tsx";

export default function Migrations() {
  return (
    <>
      <H1>Database Migrations</H1>

      <P>
        PolyArb uses Alembic for database schema management. Migrations are applied automatically
        on service startup, but can also be run manually.
      </P>

      <H2>Migration History</H2>

      <Table
        headers={["Revision", "Description"]}
        rows={[
          ["001", "markets (with pgvector Vector(384)), price_snapshots"],
          ["002", "market_pairs, arbitrage_opportunities"],
          ["003", "paper_trades, portfolio_snapshots"],
          ["004", "resolved_outcome/resolved_at on markets; nullable opportunity_id on paper_trades"],
          ["005", "source column (paper/live) on paper_trades + portfolio_snapshots"],
        ]}
      />

      <H2>Auto-Migration</H2>

      <P>
        Every service container runs <Code>alembic upgrade head</Code> before starting its main
        process. This ensures the database schema is always up to date, even across deployments.
      </P>

      <CodeBlock lang="bash">{`# From Dockerfile CMD
alembic upgrade head && python -m services.SERVICE_NAME.main`}</CodeBlock>

      <H2>Manual Operations</H2>

      <CodeBlock lang="bash">{`# Check current migration version
docker compose exec simulator alembic current

# Apply all pending migrations
docker compose exec simulator alembic upgrade head

# Create a new auto-generated migration
docker compose exec simulator \\
  alembic revision --autogenerate -m "add new column"

# Downgrade one revision
docker compose exec simulator alembic downgrade -1`}</CodeBlock>

      <H2>Backtest Database</H2>

      <P>
        The backtest database is created via <Code>dblink</Code> (copying markets/pairs from
        the live DB). Since it's created externally, it has no <Code>alembic_version</Code> table.
        You must stamp it before running migrations:
      </P>

      <CodeBlock lang="bash">{`# Stamp the backtest DB with the current revision
POSTGRES_DB=polyarb_backtest alembic stamp head`}</CodeBlock>

      <Callout type="warning">
        Never run <Code>alembic downgrade</Code> on the production database without a backup.
        Downgrade migrations may drop columns or tables with data.
      </Callout>
    </>
  );
}
