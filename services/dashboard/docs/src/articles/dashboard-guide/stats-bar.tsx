import { H1, H2, P, Code, Table, Callout } from "../../components/Prose.tsx";

export default function StatsBar() {
  return (
    <>
      <H1>Stats Bar</H1>

      <P>
        The stats bar is the top section of the dashboard showing key portfolio and system metrics.
        Each stat is clickable — tapping it navigates to the relevant tab.
      </P>

      <H2>Metrics</H2>

      <Table
        headers={["Stat", "Source", "Click Target"]}
        rows={[
          ["Active Markets", "Count of markets where active=true", "—"],
          ["Market Pairs", "Count of discovered market pairs", "Pairs tab"],
          ["Opportunities", "Total arbitrage opportunities detected", "Opportunities tab"],
          ["Cash", "portfolio.cash", "—"],
          ["Total Value", "Cash + unrealized position value", "—"],
          ["Realized PnL", "Cumulative PnL from closed/settled positions", "Trades tab"],
          ["Unrealized PnL", "Mark-to-market PnL on open positions", "Trades tab"],
        ]}
      />

      <H2>Color Coding</H2>

      <P>
        PnL values are colored based on sign:
      </P>

      <Table
        headers={["Value", "Color"]}
        rows={[
          ["Positive", <span style={{ color: "var(--color-green)" }}>Green (#00e67a)</span>],
          ["Negative", <span style={{ color: "var(--color-red)" }}>Red (#ff4444)</span>],
          ["Zero", <span style={{ color: "var(--color-text-secondary)" }}>Gray</span>],
        ]}
      />

      <H2>Win Rate</H2>

      <P>
        The win rate tooltip shows: <Code>winning_trades / settled_trades</Code>. This only counts
        trades that have been settled (market resolved), not open positions. A newly opened position
        doesn't affect win rate until settlement.
      </P>

      <Callout type="info">
        The stats bar updates in real-time via WebSocket — no need to refresh. When the mode
        switcher changes between Paper and Live, all stats reflect the selected mode.
      </Callout>
    </>
  );
}
