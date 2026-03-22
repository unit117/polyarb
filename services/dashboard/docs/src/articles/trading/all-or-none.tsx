import { H1, H2, P, Code, Callout, Diagram, UL } from "../../components/Prose.tsx";

export default function AllOrNone() {
  return (
    <>
      <H1>All-or-None Execution</H1>

      <P>
        Arbitrage trades typically have multiple legs — you need to buy one contract AND sell
        another simultaneously. If only one leg executes, you're left with directional exposure
        instead of a hedged position. PolyArb uses all-or-none execution to prevent this.
      </P>

      <H2>The Problem</H2>

      <P>
        Consider a mutual exclusion arbitrage: buy "No" on Market A and buy "Yes" on Market B.
        If only the first leg fills but the second fails (e.g., price moved, insufficient liquidity),
        you're left holding a naked "No" position — pure directional risk, not arbitrage.
      </P>

      <H2>Two-Pass Execution</H2>

      <P>
        The simulator uses a two-pass approach:
      </P>

      <Diagram>{`Pass 1: VALIDATION
  For each trade leg:
    ✓ Check price freshness (≤ 120s old)
    ✓ Compute VWAP from orderbook
    ✓ Calculate venue fees
    ✓ Validate post-VWAP edge > 0
    ✓ Run circuit breaker check
    ✓ Reserve cash for multi-leg execution

  If ANY leg fails → revert opportunity to "optimized"
                   → no trades executed

Pass 2: EXECUTION (only if all legs validated)
  For each trade leg:
    → Execute trade on portfolio
    → Persist PaperTrade to database
    → Publish trade event`}</Diagram>

      <H2>What Gets Checked</H2>

      <UL>
        <li><strong>Freshness</strong> — price snapshot must be ≤ <Code>120</Code> seconds old</li>
        <li><strong>VWAP fill</strong> — orderbook must have enough liquidity</li>
        <li><strong>Post-VWAP edge</strong> — trade must still be profitable after actual fill price + fees</li>
        <li><strong>Circuit breakers</strong> — daily loss, position limits, drawdown, consecutive errors</li>
        <li><strong>Cash reservation</strong> — enough cash for ALL legs, not just the current one</li>
      </UL>

      <H2>Cash Reservation</H2>

      <P>
        Before executing any leg, the simulator checks that the portfolio has enough cash
        for all remaining legs. This prevents a scenario where the first leg succeeds but
        there isn't enough cash left for subsequent legs.
      </P>

      <Callout type="tip">
        If any validation fails, the opportunity is reverted to <Code>optimized</Code> status.
        It will be re-evaluated in the next detection cycle with fresh prices, and may be
        traded later if conditions improve.
      </Callout>

      <H2>Why Not Partial Execution?</H2>

      <UL>
        <li>Partial fills create directional risk instead of hedged arbitrage</li>
        <li>Unwinding a partial position may incur additional slippage and fees</li>
        <li>The theoretical profit assumes all legs execute — partial execution invalidates the math</li>
        <li>Better to wait for fresh prices and retry than to hold an incomplete position</li>
      </UL>
    </>
  );
}
