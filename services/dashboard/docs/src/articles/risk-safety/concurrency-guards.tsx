import { H1, H2, P, Code, CodeBlock, Callout, UL } from "../../components/Prose.tsx";

export default function ConcurrencyGuards() {
  return (
    <>
      <H1>Concurrency Guards</H1>

      <P>
        PolyArb processes multiple opportunities concurrently via asyncio. Without proper
        synchronization, concurrent portfolio mutations could lead to data corruption —
        reading stale cash balances, double-spending, or inconsistent position tracking.
      </P>

      <H2>The Execution Lock</H2>

      <P>
        The simulator uses an <Code>asyncio.Lock</Code> to serialize all portfolio mutations:
      </P>

      <CodeBlock lang="python">{`class SimulatorPipeline:
    def __init__(self, ...):
        self._execution_lock = asyncio.Lock()

    async def simulate_opportunity(self, opportunity_id):
        async with self._execution_lock:
            return await self._simulate_opportunity_inner(opportunity_id)`}</CodeBlock>

      <P>
        This means only one opportunity can be executing trades at a time. While one
        opportunity is in its validate-then-execute cycle, all others wait for the lock.
      </P>

      <H2>What's Protected</H2>

      <P>
        The execution lock covers all operations that read or modify portfolio state:
      </P>

      <UL>
        <li><strong>Trade execution</strong> — cash deduction, position updates, cost basis tracking</li>
        <li><strong>Settlement</strong> — closing positions, calculating realized PnL</li>
        <li><strong>Purge</strong> — cleaning up resolved positions</li>
        <li><strong>Snapshot</strong> — taking portfolio snapshots for history</li>
      </UL>

      <H2>Detection Lock</H2>

      <P>
        The detector pipeline also has its own lock (<Code>_detection_lock</Code>) to prevent
        concurrent detection runs from creating duplicate pairs. This is separate from the
        execution lock — detection and execution can proceed in parallel, but two detection
        runs cannot.
      </P>

      <H2>Why Not Database-Level Locks?</H2>

      <UL>
        <li>Portfolio state is held in-memory (the <Code>Portfolio</Code> object), not just in the database</li>
        <li>A single asyncio lock is simpler and sufficient for a single-process service</li>
        <li>Database writes happen inside the lock, keeping DB and memory state consistent</li>
        <li>If PolyArb scaled to multiple processes, distributed locks (Redis SETNX) would be needed</li>
      </UL>

      <Callout type="info">
        The lock was added after a race condition was discovered where two opportunities
        arriving simultaneously could both pass cash checks before either deducted funds,
        leading to negative cash balances.
      </Callout>
    </>
  );
}
