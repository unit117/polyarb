import { H1, H2, P, Code, CodeBlock, Table, Callout, UL } from "../../components/Prose.tsx";

export default function WebSocketStreaming() {
  return (
    <>
      <H1>WebSocket Streaming</H1>

      <P>
        The dashboard receives real-time updates via WebSocket. When the system detects an
        opportunity, executes a trade, or discovers a pair, the update appears in the UI
        instantly without polling or page refreshes.
      </P>

      <H2>Architecture</H2>

      <UL>
        <li>Dashboard backend subscribes to all Redis channels (<Code>polyarb:*</Code>)</li>
        <li>Events are broadcast to all connected WebSocket clients</li>
        <li>Frontend selectively refetches data based on event type</li>
        <li>Auto-reconnect with 3-second delay on disconnect</li>
      </UL>

      <H2>WebSocket Endpoint</H2>

      <P>
        The WebSocket is available at <Code>/ws</Code> on the dashboard server (port 8080 internal,
        8081 external).
      </P>

      <CodeBlock lang="javascript">{`// Frontend WebSocket connection
const ws = new WebSocket("ws://localhost:8081/ws");

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  // data.channel = "polyarb:trade_executed"
  // data.payload = { trade_id: 42, ... }
};

ws.onclose = () => {
  // Auto-reconnect after 3 seconds
  setTimeout(() => connect(), 3000);
};`}</CodeBlock>

      <H2>Event-Driven Refetches</H2>

      <P>
        The frontend doesn't blindly refetch everything on every event. Instead, it maps
        event channels to specific data refreshes:
      </P>

      <Table
        headers={["Event Channel", "Frontend Action"]}
        rows={[
          [<Code>polyarb:arbitrage_found</Code>, "Refetch opportunities + stats"],
          [<Code>polyarb:trade_executed</Code>, "Refetch trades + stats + portfolio history"],
          [<Code>polyarb:pair_detected</Code>, "Refetch pairs + stats"],
          [<Code>polyarb:portfolio_updated</Code>, "Refetch stats + portfolio history"],
          [<Code>polyarb:market_resolved</Code>, "Refetch stats + trades"],
        ]}
      />

      <H2>Pagination Preservation</H2>

      <P>
        When a WebSocket event triggers a refetch, the frontend preserves the current pagination
        state. If you've loaded 400 items (page 1 + page 2), the refetch loads all 400 items
        again to ensure the list stays complete and in order.
      </P>

      <Callout type="tip">
        The WebSocket connection status can be monitored in the browser's Network tab.
        If you see frequent reconnections, check that the dashboard container is healthy
        and Redis is responding.
      </Callout>
    </>
  );
}
