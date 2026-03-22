import { H1, H2, P, Code, Table, Callout } from "../../components/Prose.tsx";

export default function PairsTable() {
  return (
    <>
      <H1>Pairs Table</H1>

      <P>
        The pairs table shows all discovered market pair relationships. Each row represents
        a logical dependency between two markets that PolyArb is monitoring for arbitrage.
      </P>

      <H2>Columns</H2>

      <Table
        headers={["Column", "Description"]}
        rows={[
          ["Market A", "First market question (abbreviated)"],
          ["Market B", "Second market question (abbreviated)"],
          ["Type", "Dependency type"],
          ["Confidence", "LLM classification confidence (0-100%)"],
          ["Verified", "Whether manually verified"],
          ["Opportunities", "Number of arbitrage opportunities detected for this pair"],
        ]}
      />

      <H2>Dependency Type Badges</H2>

      <Table
        headers={["Type", "Badge Color", "Meaning"]}
        rows={[
          [<Code>mutual_exclusion</Code>, "Red", "Both can't be true"],
          [<Code>partition</Code>, "Purple", "Exhaustive + exclusive outcomes"],
          [<Code>conditional</Code>, "Blue", "One implies the other"],
          [<Code>cross_platform</Code>, "Orange", "Same event on different venues"],
        ]}
      />

      <H2>Confidence Meter</H2>

      <P>
        Each pair shows a confidence bar from 0-100%. This is the LLM's confidence
        in its dependency classification. Higher confidence means the logical relationship
        is more certain.
      </P>

      <Table
        headers={["Confidence", "Interpretation"]}
        rows={[
          ["90-100%", "Very high confidence — clear logical relationship"],
          ["70-90%", "Good confidence — relationship likely correct"],
          ["50-70%", "Moderate — may need manual verification"],
          ["<50%", "Low confidence — relationship uncertain"],
        ]}
      />

      <Callout type="info">
        Cross-platform pairs auto-classified at similarity ≥ 0.92 always get a confidence
        of 95%. LLM-classified pairs have variable confidence based on the model's assessment.
      </Callout>
    </>
  );
}
