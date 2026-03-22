import { H1, H2, P, Code, Callout, UL } from "../../components/Prose.tsx";

export default function Deduplication() {
  return (
    <>
      <H1>Deduplication</H1>

      <P>
        The same arbitrage opportunity can be detected multiple times — on each detection cycle,
        during rescans, or when prices fluctuate around the profitability threshold. Deduplication
        prevents the simulator from trading the same opportunity multiple times.
      </P>

      <H2>In-Flight Tracking</H2>

      <P>
        The simulator maintains an <Code>_in_flight</Code> set of opportunity IDs currently
        being processed. When a new opportunity arrives:
      </P>

      <UL>
        <li>Check if <Code>opportunity_id</Code> is in the in-flight set</li>
        <li>If yes → skip with reason <Code>"in_flight"</Code></li>
        <li>If no → add to set and proceed</li>
        <li>Remove from set when processing completes (success or failure)</li>
      </UL>

      <H2>Status-Based Filtering</H2>

      <P>
        The simulator only processes opportunities with specific statuses:
      </P>

      <UL>
        <li><Code>optimized</Code> — Frank-Wolfe converged, ready for execution</li>
        <li><Code>unconverged</Code> — Frank-Wolfe hit iteration limit, may still trade</li>
      </UL>

      <P>
        Opportunities in other states are automatically skipped:
      </P>

      <UL>
        <li><Code>detected</Code> — awaiting optimization, not ready</li>
        <li><Code>pending</Code> — already being executed</li>
        <li><Code>executed</Code> — already traded</li>
        <li><Code>expired</Code> — profit disappeared</li>
      </UL>

      <H2>Pair-Level Dedup</H2>

      <P>
        The detector also prevents duplicate pairs. When scanning for new pairs, it checks
        whether a pair already exists for the same two markets (in either order) and skips
        it if so.
      </P>

      <Callout type="info">
        The combination of in-flight tracking, status filtering, and pair-level dedup ensures
        that each real arbitrage opportunity is traded at most once, even in a concurrent
        environment.
      </Callout>
    </>
  );
}
