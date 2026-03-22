import { H1, H2, P, Callout, UL } from "../../components/Prose.tsx";

export default function MetricsPanel() {
  return (
    <>
      <H1>Metrics Panel</H1>

      <P>
        The metrics panel provides system-level analytics — how well the pipeline is performing,
        conversion rates through the funnel, and activity trends over time.
      </P>

      <H2>Opportunity Funnel</H2>

      <P>
        Shows the pipeline conversion rate:
      </P>

      <UL>
        <li><strong>Detected</strong> — total opportunities found (constraint violations)</li>
        <li><strong>Optimized</strong> — passed Frank-Wolfe optimization</li>
        <li><strong>Traded</strong> — actually executed (all legs filled)</li>
        <li><strong>Expired</strong> — profit disappeared before execution</li>
      </UL>

      <P>
        A healthy funnel shows most detected opportunities getting optimized, with a reasonable
        fraction being traded and the rest expiring. A high expiration rate may indicate stale
        prices or slow execution.
      </P>

      <H2>Hit Rate</H2>

      <P>
        The percentage of optimized opportunities that were successfully traded
        (vs expired or blocked). A high hit rate means the system is executing efficiently.
      </P>

      <H2>Duration Histogram</H2>

      <P>
        Shows the distribution of how long opportunities lasted before being executed or
        expiring. Short durations (seconds to minutes) are typical — arbitrage windows
        close quickly as markets reprice.
      </P>

      <H2>Hourly Timeseries</H2>

      <P>
        Charts showing activity over the last 24 hours:
      </P>

      <UL>
        <li><strong>Detections per hour</strong> — how many new opportunities were found</li>
        <li><strong>Trades per hour</strong> — execution activity</li>
        <li><strong>Volume per hour</strong> — total dollar amount traded</li>
        <li><strong>Fees per hour</strong> — total fees paid</li>
      </UL>

      <Callout type="tip">
        Use the timeseries to spot patterns — for example, if detections spike during certain
        hours (around news events or market opens), that tells you when the most profitable
        windows occur.
      </Callout>
    </>
  );
}
