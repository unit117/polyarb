import { H1, H2, H3, P, Code, Diagram, Table, Callout, UL } from "../../components/Prose.tsx";

export default function DetectionPipeline() {
  return (
    <>
      <H1>Arbitrage Detection Pipeline</H1>

      <P>
        The detection pipeline is the heart of PolyArb. It runs every 60 seconds, discovering
        new market pairs, validating constraints, computing theoretical profits, and publishing
        opportunities for optimization.
      </P>

      <H2>Pipeline Flow</H2>

      <Diagram>{`┌─────────────────┐
│  find_similar   │  pgvector cosine similarity ≥ 0.82
│     _pairs()    │  top-20 per market, batch of 100
└────────┬────────┘
         ▼
┌─────────────────┐
│ classify_pair() │  GPT-4.1-mini dependency classification
│                 │  Returns type + confidence
└────────┬────────┘
         ▼
┌─────────────────┐
│ build_constraint│  Construct feasibility matrix
│    _matrix()    │  from classification results
└────────┬────────┘
         ▼
┌─────────────────┐
│  verify_pair()  │  Validate constraint consistency
│                 │  Check for profit > 0
└────────┬────────┘
         ▼
┌─────────────────┐
│    Persist &    │  Store MarketPair + ArbitrageOpportunity
│    Publish      │  Publish to Redis channels
└─────────────────┘`}</Diagram>

      <H2>Step 1: Find Similar Pairs</H2>

      <P>
        The pipeline queries pgvector for candidate pairs. For each market in a batch
        of <Code>100</Code>, it finds up to <Code>20</Code> similar markets above
        the <Code>0.82</Code> similarity threshold. Pairs that already exist in the
        database are skipped.
      </P>

      <H2>Step 2: Classify Dependencies</H2>

      <P>
        Candidate pairs are sent to <Code>gpt-4.1-mini</Code> for classification. The LLM
        analyzes both market questions and determines:
      </P>

      <UL>
        <li>The dependency type (mutual_exclusion, partition, conditional, cross_platform)</li>
        <li>A confidence score (0 to 1)</li>
        <li>The logical relationship between outcomes</li>
      </UL>

      <H3>Cross-Venue Auto-Classification</H3>

      <P>
        When markets are from different venues (Polymarket vs Kalshi) and similarity
        is ≥ <Code>0.92</Code>, the pair is auto-classified as <Code>cross_platform</Code> with
        confidence <Code>0.95</Code>, bypassing the LLM call.
      </P>

      <H2>Step 3: Build Constraint Matrix</H2>

      <P>
        The classification result is converted into a feasibility matrix. This matrix defines
        which joint outcome combinations are possible (1) or impossible (0). The theoretical
        profit is computed from the matrix and current prices.
      </P>

      <H2>Step 4: Verify & Persist</H2>

      <P>
        Valid pairs with positive theoretical profit are stored and published:
      </P>

      <UL>
        <li><Code>MarketPair</Code> record created with constraint matrix</li>
        <li><Code>ArbitrageOpportunity</Code> record created with status <Code>detected</Code></li>
        <li>Events published: <Code>polyarb:pair_detected</Code>, <Code>polyarb:arbitrage_found</Code></li>
      </UL>

      <H2>Rescan Existing Pairs</H2>

      <P>
        The pipeline also rescans existing pairs with fresh price data. This catches:
      </P>

      <UL>
        <li><strong>Expired opportunities</strong> — profit has disappeared, marked as "expired"</li>
        <li><strong>Stale optimizations</strong> — optimized/unconverged opps reset to "detected" for fresh optimization</li>
        <li><strong>New opportunities</strong> — price changes create new profit on existing pairs</li>
      </UL>

      <H2>Opportunity States</H2>

      <Table
        headers={["Status", "Meaning", "Next Step"]}
        rows={[
          [<Code>detected</Code>, "Profit identified, awaiting optimization", "Optimizer runs Frank-Wolfe"],
          [<Code>optimized</Code>, "Frank-Wolfe converged, trades computed", "Simulator executes"],
          [<Code>unconverged</Code>, "Frank-Wolfe hit iteration limit", "May still be traded"],
          [<Code>pending</Code>, "Simulator is actively executing", "Awaiting trade completion"],
          [<Code>executed</Code>, "All trade legs filled", "Positions held until settlement"],
          [<Code>expired</Code>, "Profit disappeared before execution", "No action needed"],
        ]}
      />

      <Callout type="info">
        The detection pipeline is serialized with an asyncio lock to prevent concurrent runs
        from creating duplicate pairs.
      </Callout>
    </>
  );
}
