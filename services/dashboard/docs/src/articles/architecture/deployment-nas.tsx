import { H1, H2, P, Code, CodeBlock, Callout, UL } from "../../components/Prose.tsx";

export default function DeploymentNas() {
  return (
    <>
      <H1>Deployment & NAS Setup</H1>

      <P>
        PolyArb runs on a Synology NAS. Deployment is done
        from a local Mac via tar-over-SSH (scp doesn't work on Synology).
      </P>

      <H2>Deployment Workflow</H2>

      <CodeBlock lang="bash">{`# 1. Package the codebase (excluding heavy directories)
tar czf /tmp/polyarb.tar.gz \\
  --exclude='node_modules' \\
  --exclude='.git' \\
  --exclude='__pycache__' \\
  --exclude='.env' .

# 2. Upload and extract on NAS
cat /tmp/polyarb.tar.gz | ssh $NAS_USER@$NAS_HOST \\
  "cd /volume1/docker/polyarb && \\
   cat > x.tar.gz && \\
   tar xzf x.tar.gz && \\
   rm x.tar.gz && \\
   find . -name '._*' -delete"

# 3. Rebuild and restart services
ssh $NAS_USER@$NAS_HOST \\
  "cd /volume1/docker/polyarb && \\
   docker compose build && \\
   docker compose up -d"`}</CodeBlock>

      <Callout type="warning">
        The <Code>find . -name '._*' -delete</Code> step is important — macOS creates resource
        fork files that can confuse Docker builds.
      </Callout>

      <H2>Rebuilding a Single Service</H2>

      <CodeBlock lang="bash">{`ssh $NAS_USER@$NAS_HOST \\
  "cd /volume1/docker/polyarb && \\
   docker compose build simulator && \\
   docker compose up -d simulator"`}</CodeBlock>

      <H2>Viewing Logs</H2>

      <CodeBlock lang="bash">{`# Follow logs for a specific service
ssh $NAS_USER@$NAS_HOST \\
  "cd /volume1/docker/polyarb && \\
   docker compose logs -f simulator"

# Last 100 lines
ssh $NAS_USER@$NAS_HOST \\
  "cd /volume1/docker/polyarb && \\
   docker compose logs --tail=100 simulator"`}</CodeBlock>

      <H2>Port Assignments</H2>

      <P>
        Ports 5432, 5433, 6379, and 8080 are already in use on the NAS by other services.
        PolyArb uses offset ports:
      </P>

      <UL>
        <li>PostgreSQL: <Code>5434</Code> (host) → 5432 (container)</li>
        <li>Redis: <Code>6380</Code> (host) → 6379 (container)</li>
        <li>Dashboard: <Code>8081</Code> (host) → 8080 (container)</li>
      </UL>

      <H2>Database Migrations</H2>

      <P>
        Migrations run automatically on service startup via the entrypoint script:
      </P>

      <CodeBlock lang="bash">{`# The CMD in each Dockerfile
alembic upgrade head && python -m services.SERVICE_NAME.main`}</CodeBlock>

      <P>
        To manually run migrations:
      </P>

      <CodeBlock lang="bash">{`# Check current migration
ssh $NAS_USER@$NAS_HOST \\
  "cd /volume1/docker/polyarb && \\
   docker compose exec simulator alembic current"

# Create new migration
docker compose exec simulator \\
  alembic revision --autogenerate -m "description"`}</CodeBlock>

      <H2>Gotchas</H2>

      <UL>
        <li><Code>scp</Code> doesn't work on Synology — use tar-over-SSH pipe instead</li>
        <li>macOS creates <Code>._*</Code> resource forks — delete them before building</li>
        <li>If <Code>npm install</Code> fails on macOS (native modules), wipe <Code>node_modules</Code> and <Code>package-lock.json</Code></li>
        <li>Backtest DB (created via dblink) has no <Code>alembic_version</Code> — stamp before upgrading</li>
        <li>CLOB API rejects history requests for intervals {">"} ~14 days — chunk requests</li>
      </UL>
    </>
  );
}
