import { H1, H2, P, Code, Table, Callout, CodeBlock, UL } from "../../components/Prose.tsx";

export default function DependencyTypes() {
  return (
    <>
      <H1>Dependency Types</H1>

      <P>
        PolyArb recognizes four types of logical relationships between markets. Each type implies
        specific constraints on valid price combinations, and violations of these constraints
        represent arbitrage opportunities.
      </P>

      <H2>Mutual Exclusion</H2>

      <P>
        Two outcomes that cannot both be true. The sum of their Yes prices must not exceed $1.00.
      </P>

      <Table
        headers={["Constraint", "Arbitrage Signal"]}
        rows={[
          ["P(A) + P(B) ≤ 1", "P(A_yes) + P(B_yes) > 1"],
        ]}
      />

      <P>
        <strong>Example:</strong> "Will candidate X win the primary?" and "Will candidate Y win
        the primary?" — both can't win, so their Yes prices should sum to at most $1.
      </P>

      <CodeBlock lang="text">{`Constraint matrix (mutual exclusion):
       B=Yes  B=No
A=Yes  [ 0     1  ]   ← A=Yes AND B=Yes is impossible
A=No   [ 1     1  ]`}</CodeBlock>

      <H2>Partition</H2>

      <P>
        A set of outcomes that are exhaustive and mutually exclusive — exactly one must occur.
        Their Yes prices must sum to exactly $1.00.
      </P>

      <Table
        headers={["Constraint", "Arbitrage Signal"]}
        rows={[
          ["P(A₁) + P(A₂) + ... + P(Aₙ) = 1", "Sum deviates from 1.00"],
        ]}
      />

      <P>
        <strong>Example:</strong> All candidates for a single seat form a partition — exactly one
        will win. If their prices sum to $1.05, you can sell all outcomes for $1.05 and pay out
        exactly $1.00, pocketing $0.05.
      </P>

      <H2>Conditional (Implication)</H2>

      <P>
        One outcome logically implies another. If A is true, then B must also be true, so
        P(A) ≤ P(B).
      </P>

      <Table
        headers={["Constraint", "Arbitrage Signal"]}
        rows={[
          ["P(A) ≤ P(B)", "P(A_yes) > P(B_yes)"],
        ]}
      />

      <P>
        <strong>Example:</strong> "Will the Fed raise rates in June?" implies "Will the Fed raise
        rates in 2024?" If June is priced higher than 2024, that's a violation.
      </P>

      <Callout type="info">
        Conditional pairs are currently skipped by the optimizer (<Code>optimizer_skip_conditional = True</Code>)
        because they tend to produce thin margins after costs. This may change as the system matures.
      </Callout>

      <H2>Cross-Platform</H2>

      <P>
        The same event traded on different venues (e.g., Polymarket and Kalshi). Prices should
        be nearly identical, but venue-specific liquidity and fee structures create spreads.
      </P>

      <Table
        headers={["Constraint", "Arbitrage Signal"]}
        rows={[
          ["P_poly(A) ≈ P_kalshi(A)", "Significant price divergence between venues"],
        ]}
      />

      <P>
        Cross-platform pairs are auto-classified when embedding similarity is ≥ <Code>0.92</Code> with
        a confidence of 0.95. Below that threshold, LLM classification is used.
      </P>

      <H2>Classification Pipeline</H2>

      <UL>
        <li>Embedding similarity ≥ <Code>0.82</Code> → candidate pair</li>
        <li>Cross-venue + similarity ≥ <Code>0.92</Code> → auto-classify as cross_platform</li>
        <li>Otherwise → <Code>gpt-4.1-mini</Code> classifies type + confidence</li>
        <li>Constraint matrix built from classification result</li>
        <li>Pair stored with confidence score for tracking</li>
      </UL>
    </>
  );
}
