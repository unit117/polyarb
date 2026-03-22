import { H1, H2, P, Code, Table, Callout, UL } from "../../components/Prose.tsx";

export default function OpportunitiesTable() {
  return (
    <>
      <H1>Opportunities Table</H1>

      <P>
        The opportunities table shows every arbitrage opportunity the system has detected.
        It's the primary view for understanding what PolyArb is finding and doing.
      </P>

      <H2>Columns</H2>

      <Table
        headers={["Column", "Description"]}
        rows={[
          ["Time", "When the opportunity was detected"],
          ["Pair", "The two markets involved (abbreviated questions)"],
          ["Type", "Dependency type (mutual_exclusion, partition, etc.)"],
          ["Theoretical", "Raw profit from constraint violation (before costs)"],
          ["Estimated", "Profit after fees and slippage (from optimizer)"],
          ["FW Iters", "Frank-Wolfe iterations to convergence"],
          ["Gap", "Final Bregman/duality gap (lower = more optimal)"],
          ["Status", "Current state (detected, optimized, executed, expired, etc.)"],
        ]}
      />

      <H2>Status Colors</H2>

      <Table
        headers={["Status", "Color", "Meaning"]}
        rows={[
          [<Code>detected</Code>, "Blue", "Awaiting optimization"],
          [<Code>optimized</Code>, "Green", "Ready for execution"],
          [<Code>unconverged</Code>, "Yellow", "FW didn't converge, may still trade"],
          [<Code>pending</Code>, "Orange", "Currently being executed"],
          [<Code>executed</Code>, "Green (bright)", "All trade legs filled"],
          [<Code>expired</Code>, "Gray", "Profit disappeared before execution"],
        ]}
      />

      <H2>Filtering</H2>

      <P>
        There's a toggle to show/hide unprofitable opportunities (where estimated profit ≤ 0
        after costs). By default, these are hidden to focus on actionable opportunities.
      </P>

      <H2>Detail Panel</H2>

      <P>
        Click any row to open a slide-out detail panel showing:
      </P>

      <UL>
        <li>Full market questions for both sides of the pair</li>
        <li>Dependency type and confidence score</li>
        <li>Frank-Wolfe convergence details (iterations, gap, KL divergence)</li>
        <li>Individual trade legs with prices and sizes</li>
        <li>Profit breakdown (theoretical vs estimated)</li>
        <li>Duration (for expired opportunities — how long the window lasted)</li>
      </UL>

      <Callout type="tip">
        Press <Code>Escape</Code> to close the detail panel, or click anywhere outside it.
      </Callout>

      <H2>Pagination</H2>

      <P>
        The table loads 200 rows at a time. A "Load More" button at the bottom fetches the
        next page. The loaded count persists across WebSocket refetches — if you've loaded
        400 items, a real-time update will re-fetch all 400.
      </P>
    </>
  );
}
