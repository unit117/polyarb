import { H1, H2, P, Code, Table, Callout, CodeBlock, DashboardLink, UL } from "../../components/Prose.tsx";

export default function MarketPairs() {
  return (
    <>
      <H1>Market Pairs & Dependencies</H1>

      <P>
        The foundation of arbitrage detection is discovering which markets are logically related.
        PolyArb pairs markets whose outcomes have a mathematical dependency — meaning the price
        of one constrains the valid price range of the other.
      </P>

      <H2>How Pairs Are Discovered</H2>

      <P>
        The detector service runs a three-stage pipeline every 60 seconds:
      </P>

      <UL>
        <li><strong>Embedding similarity</strong> — each market question is embedded using OpenAI's <Code>text-embedding-3-small</Code> model (384 dimensions). pgvector finds the top-20 most similar markets above a cosine similarity threshold of <Code>0.82</Code>.</li>
        <li><strong>LLM classification</strong> — candidate pairs are sent to <Code>gpt-4.1-mini</Code> which classifies the dependency type and assigns a confidence score.</li>
        <li><strong>Constraint matrix construction</strong> — for validated pairs, a feasibility matrix is built defining which joint outcome combinations are possible.</li>
      </UL>

      <H2>The MarketPair Record</H2>

      <P>
        Each discovered pair is stored in the <Code>market_pairs</Code> table with:
      </P>

      <Table
        headers={["Field", "Description"]}
        rows={[
          [<Code>market_a_id</Code>, "First market in the pair"],
          [<Code>market_b_id</Code>, "Second market in the pair"],
          [<Code>dependency_type</Code>, "Type of logical relationship"],
          [<Code>confidence</Code>, "LLM-derived confidence score (0-1)"],
          [<Code>constraint_matrix</Code>, "JSONB with feasibility matrix, outcomes, profit bound"],
          [<Code>verified</Code>, "Whether the pair has been manually verified"],
        ]}
      />

      <H2>Constraint Matrix</H2>

      <P>
        The constraint matrix defines which combinations of outcomes from Market A and Market B
        are jointly feasible. For a mutual exclusion pair (both can't be Yes):
      </P>

      <CodeBlock lang="json">{`{
  "type": "mutual_exclusion",
  "outcomes_a": ["Yes", "No"],
  "outcomes_b": ["Yes", "No"],
  "matrix": [
    [0, 1],
    [1, 1]
  ],
  "profit_bound": 0.10,
  "correlation": -0.85
}`}</CodeBlock>

      <P>
        A <Code>1</Code> means that combination is feasible; <Code>0</Code> means impossible.
        In this example, both being Yes (top-left) is impossible, which is the mutual exclusion
        constraint.
      </P>

      <Callout type="info">
        The profit bound is the maximum theoretical arbitrage profit based on current prices
        and the constraint matrix. The optimizer uses this as a starting point for Frank-Wolfe
        optimization.
      </Callout>

      <P>
        View all discovered pairs in the <DashboardLink tab="pairs">Pairs table</DashboardLink>.
      </P>
    </>
  );
}
