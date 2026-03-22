import { H1, H2, P, Code, Table, Callout } from "../../components/Prose.tsx";

export default function TradesTable() {
  return (
    <>
      <H1>Trades Table</H1>

      <P>
        The trades table shows all executed trade legs, grouped by the opportunity that
        triggered them. Each arbitrage opportunity typically produces 2+ trade legs
        (one for each side of the pair).
      </P>

      <H2>Columns</H2>

      <Table
        headers={["Column", "Description"]}
        rows={[
          ["Time", "When the trade was executed"],
          ["Opportunity", "ID of the parent opportunity (groups trades together)"],
          ["Market", "Which market was traded"],
          ["Outcome", "Which outcome (Yes/No or specific)"],
          ["Side", "BUY or SELL"],
          ["Size", "Number of contracts traded"],
          ["Entry Price", "Price from optimization/constraint"],
          ["VWAP Price", "Actual fill price from orderbook walk"],
          ["Slippage", "Execution slippage percentage"],
          ["Fees", "Venue fees paid"],
          ["Venue", "polymarket or kalshi"],
        ]}
      />

      <H2>Grouping</H2>

      <P>
        Trades are visually grouped by <Code>opportunity_id</Code>. All legs of the same
        arbitrage trade appear together, making it easy to see the complete position.
        The first row in each group shows the opportunity ID as a header.
      </P>

      <H2>Reading a Trade</H2>

      <P>
        A typical arbitrage trade has two legs:
      </P>

      <Table
        headers={["Leg", "Market", "Side", "Size", "VWAP", "Fees"]}
        rows={[
          ["1", "\"Will X happen?\"", "SELL", "50", "$0.72", "$0.003"],
          ["2", "\"Will Y happen?\"", "BUY", "50", "$0.35", "$0.003"],
        ]}
      />

      <P>
        Here, we're selling Yes on Market X at $0.72 and buying Yes on Market Y at $0.35.
        If X and Y are mutually exclusive, at most one can be true, so our maximum payout
        is $50 (one contract pays $1) against a net cost well below that.
      </P>

      <Callout type="info">
        The difference between Entry Price and VWAP Price shows how much the actual fill
        deviated from the optimized price. Large deviations may indicate thin orderbooks.
      </Callout>
    </>
  );
}
