import { H1, H2, H3, P, Code, Table, Callout, CodeBlock, UL } from "../../components/Prose.tsx";

export default function WhatIsArbitrage() {
  return (
    <>
      <H1>What is Arbitrage?</H1>

      <P>
        Arbitrage is the simultaneous purchase and sale of related assets to profit from price
        inconsistencies. In prediction markets, this means finding groups of contracts whose prices
        violate logical constraints — and trading them to lock in a guaranteed profit regardless of
        which outcome occurs.
      </P>

      <H2>Simple Example</H2>

      <P>
        Suppose two markets exist on the same event:
      </P>

      <Table
        headers={["Market", "Yes Price", "No Price"]}
        rows={[
          ["Market A: \"Will X happen?\"", "$0.70", "$0.35"],
          ["Market B: \"Will X happen?\"", "$0.60", "$0.45"],
        ]}
      />

      <P>
        Market A thinks there's a 70% chance, Market B thinks 60%. You can buy "No" on Market A
        at $0.35 and buy "Yes" on Market B at $0.60. Total cost: $0.95. No matter what happens,
        one of these contracts pays $1.00. That's a guaranteed $0.05 profit per contract.
      </P>

      <Callout type="info">
        This is a <strong>cross-market arbitrage</strong> — the same event priced differently on
        two venues. PolyArb also finds <strong>combinatorial arbitrage</strong> across logically
        related but distinct events.
      </Callout>

      <H2>Combinatorial Arbitrage</H2>

      <P>
        The more interesting (and common) case involves markets that are logically related but not
        identical. Consider:
      </P>

      <UL>
        <li>Market A: "Will the Fed raise rates in June?" — Yes at $0.40</li>
        <li>Market B: "Will the Fed raise rates in 2024?" — Yes at $0.30</li>
      </UL>

      <P>
        If the Fed raises rates in June, they've necessarily raised rates in 2024. So
        P(June) must be ≤ P(2024). Here, $0.40 {">"} $0.30 — a violation. You can sell June at
        $0.40 and buy 2024 at $0.30, locking in a $0.10 spread.
      </P>

      <H2>Dependency Types</H2>

      <P>
        PolyArb recognizes four types of logical relationships between markets:
      </P>

      <Table
        headers={["Type", "Constraint", "Example"]}
        rows={[
          ["Mutual Exclusion", "P(A) + P(B) ≤ 1", "Two candidates for the same position"],
          ["Partition", "P(A₁) + P(A₂) + ... = 1", "All candidates for a single seat"],
          ["Conditional (Implication)", "P(A) ≤ P(B)", "\"June rate hike\" implies \"2024 rate hike\""],
          ["Conditional (Reverse)", "P(A) ≥ P(B)", "Broader event implies narrower sub-event"],
        ]}
      />

      <H2>The Math Behind It</H2>

      <H3>Theoretical Profit</H3>

      <P>
        For a pair of markets with a constraint violation, the theoretical profit is the maximum
        guaranteed profit per dollar of exposure. For a mutual exclusion pair:
      </P>

      <CodeBlock lang="text">{`theoretical_profit = max(0, P(A_yes) + P(B_yes) - 1)`}</CodeBlock>

      <P>
        If Market A Yes is $0.65 and Market B Yes is $0.45, the theoretical profit
        is <Code>0.65 + 0.45 - 1 = 0.10</Code>, or 10 cents per dollar.
      </P>

      <H3>Estimated Profit</H3>

      <P>
        The estimated profit accounts for real-world costs — trading fees, orderbook slippage,
        and execution uncertainty. PolyArb's optimizer computes this using Frank-Wolfe optimization
        to find the portfolio that maximizes risk-free profit after costs.
      </P>

      <H2>Why It's Hard</H2>

      <UL>
        <li><strong>Discovery</strong> — there are thousands of markets; finding related pairs is a needle-in-a-haystack problem (solved with embeddings)</li>
        <li><strong>Speed</strong> — prices change fast; stale prices lead to phantom opportunities</li>
        <li><strong>Costs</strong> — fees and slippage eat into thin margins</li>
        <li><strong>Sizing</strong> — trading too much moves the price against you; too little isn't worth the effort</li>
        <li><strong>Execution</strong> — you need to trade both legs simultaneously or risk one leg failing</li>
      </UL>

      <Callout type="tip">
        PolyArb addresses each of these challenges: pgvector for discovery, freshness bounds for
        staleness, VWAP for slippage modeling, Kelly criterion for sizing, and all-or-none execution
        for safety.
      </Callout>
    </>
  );
}
