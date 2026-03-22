import { H1, H2, P, Code, Callout, UL } from "../../components/Prose.tsx";

export default function FreshnessBounds() {
  return (
    <>
      <H1>Freshness Bounds</H1>

      <P>
        Price data goes stale quickly in prediction markets. A price that was valid 5 minutes
        ago may have moved significantly. Freshness bounds prevent PolyArb from trading on
        outdated information.
      </P>

      <H2>The Rule</H2>

      <P>
        Before executing any trade leg, the simulator checks the age of the latest price
        snapshot. If the snapshot is older than <Code>max_snapshot_age_seconds = 120</Code> (2 minutes),
        the trade leg is rejected.
      </P>

      <H2>Where It's Checked</H2>

      <P>
        Freshness is enforced at multiple points:
      </P>

      <UL>
        <li><strong>Simulator validation pass</strong> — each trade leg's price must be ≤ 120s old</li>
        <li><strong>Detector rescan</strong> — stale prices trigger re-evaluation of existing opportunities</li>
        <li><strong>Optimizer input</strong> — uses the latest available prices for each market</li>
      </UL>

      <H2>Why 120 Seconds?</H2>

      <UL>
        <li>The ingestor fetches new snapshots every 60 seconds</li>
        <li>120 seconds allows for one missed cycle (network hiccup, API delay)</li>
        <li>Beyond 2 minutes, prices may have moved enough to invalidate the arbitrage</li>
        <li>Combined with post-VWAP edge validation, this creates a tight safety window</li>
      </UL>

      <H2>What Happens on Stale Data</H2>

      <P>
        When a trade leg fails the freshness check:
      </P>

      <UL>
        <li>The entire opportunity (all legs) is blocked (all-or-none execution)</li>
        <li>The opportunity reverts to <Code>optimized</Code> status</li>
        <li>It will be re-evaluated in the next detection cycle with fresh prices</li>
        <li>No partial trades are executed</li>
      </UL>

      <Callout type="tip">
        If you see many opportunities being blocked for staleness, check the ingestor logs —
        it may be falling behind on price updates, or the CLOB API may be rate-limiting.
      </Callout>
    </>
  );
}
