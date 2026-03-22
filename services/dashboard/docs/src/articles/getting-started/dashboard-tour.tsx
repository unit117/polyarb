import { H1, H2, P, DashboardLink, Callout, UL } from "../../components/Prose.tsx";

export default function DashboardTour() {
  return (
    <>
      <H1>Quick Tour of the Dashboard</H1>

      <P>
        The PolyArb dashboard is a real-time monitoring interface that shows you everything the
        system is doing — from detected opportunities to executed trades to portfolio performance.
        Here's a quick walkthrough of the main sections.
      </P>

      <H2>Header</H2>

      <P>
        The header shows the system title and a Paper/Live mode switcher. Paper mode shows simulated
        trades; Live mode shows real trades (when enabled). A green pulsing dot appears next to "Live"
        when live trading is active.
      </P>

      <H2>Stats Bar</H2>

      <P>
        The top stats bar shows key portfolio metrics at a glance:
      </P>

      <UL>
        <li><strong>Active Markets</strong> — number of markets currently being tracked</li>
        <li><strong>Market Pairs</strong> — number of correlated pairs discovered</li>
        <li><strong>Opportunities</strong> — total arbitrage opportunities detected</li>
        <li><strong>Cash</strong> — available cash in the portfolio</li>
        <li><strong>Total Value</strong> — cash + unrealized position value</li>
        <li><strong>Realized PnL</strong> — profit/loss from closed trades</li>
        <li><strong>Unrealized PnL</strong> — profit/loss on open positions</li>
      </UL>

      <Callout type="tip">
        Click on any stat to jump to the relevant tab. For example, clicking "Market Pairs"
        takes you to the Pairs tab.
      </Callout>

      <H2>PnL Chart</H2>

      <P>
        Below the stats bar is a 24-hour portfolio value chart with four series: total value,
        cash, realized PnL, and unrealized PnL. This updates in real-time via WebSocket.
      </P>

      <H2>Tab Navigation</H2>

      <P>
        Four tabs let you explore different aspects of the system:
      </P>

      <H2>Opportunities Tab</H2>

      <P>
        The <DashboardLink tab="opportunities">Opportunities table</DashboardLink> shows
        every arbitrage opportunity the system has detected. Each row shows the market pair,
        dependency type, theoretical profit, estimated profit (after costs), Frank-Wolfe iterations,
        and status. Click any row to open a detailed side panel with convergence metrics and
        profit analysis.
      </P>

      <H2>Trades Tab</H2>

      <P>
        The <DashboardLink tab="trades">Trades table</DashboardLink> shows executed paper
        trades, grouped by the opportunity that triggered them. Each trade shows the market,
        side (buy/sell), size, entry price, VWAP execution price, slippage, and fees.
      </P>

      <H2>Pairs Tab</H2>

      <P>
        The <DashboardLink tab="pairs">Pairs table</DashboardLink> shows all discovered
        market pair relationships. Each pair has a dependency type (mutual exclusion, partition,
        conditional, implication), a confidence score, and a verification status. Click to see
        the individual markets in each pair.
      </P>

      <H2>Metrics Tab</H2>

      <P>
        The <DashboardLink tab="metrics">Metrics panel</DashboardLink> shows system-level
        analytics: the opportunity funnel (detected → validated → traded), hit rates, trade
        duration histogram, and hourly timeseries of activity.
      </P>

      <H2>Real-Time Updates</H2>

      <P>
        Everything updates in real-time via WebSocket. When the system detects a new opportunity,
        executes a trade, or discovers a new pair, you'll see it appear immediately without refreshing.
        The WebSocket auto-reconnects if the connection drops.
      </P>
    </>
  );
}
