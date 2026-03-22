import { H1, H2, P, Code, Table, CodeBlock, Callout } from "../../components/Prose.tsx";

export default function RedisEventBus() {
  return (
    <>
      <H1>Redis Event Bus</H1>

      <P>
        Services communicate through Redis pub/sub channels. When something happens (new market,
        opportunity detected, trade executed), the responsible service publishes an event, and
        interested services subscribe and react.
      </P>

      <H2>Channel Reference</H2>

      <Table
        headers={["Channel", "Publisher", "Subscribers", "Payload"]}
        rows={[
          [<Code>polyarb:market_updated</Code>, "Ingestor", "Detector", "Market ID + updated fields"],
          [<Code>polyarb:snapshot_created</Code>, "Ingestor", "Detector, Simulator", "Snapshot ID + market ID"],
          [<Code>polyarb:pair_detected</Code>, "Detector", "Dashboard", "Pair ID + market details"],
          [<Code>polyarb:arbitrage_found</Code>, "Detector", "Optimizer, Dashboard", "Opportunity ID + profit"],
          [<Code>polyarb:optimization_complete</Code>, "Optimizer", "Simulator, Dashboard", "Opportunity ID + result"],
          [<Code>polyarb:trade_executed</Code>, "Simulator", "Dashboard", "Trade details + PnL"],
          [<Code>polyarb:portfolio_updated</Code>, "Simulator", "Dashboard", "Portfolio snapshot"],
          [<Code>polyarb:market_resolved</Code>, "Ingestor", "Simulator", "Market ID + outcome"],
        ]}
      />

      <H2>Special Channels</H2>

      <Table
        headers={["Channel/Key", "Purpose"]}
        rows={[
          [<Code>polyarb:circuit_breaker_tripped</Code>, "Published when a circuit breaker trips with the reason"],
          [<Code>polyarb:kill_switch</Code>, "Redis key (not channel) — when set, blocks all trading"],
        ]}
      />

      <H2>Event Flow Example</H2>

      <P>
        Here's what happens when a new arbitrage opportunity is found:
      </P>

      <CodeBlock lang="text">{`1. Ingestor publishes polyarb:snapshot_created
   → Detector receives, rescans pairs involving that market

2. Detector finds price violation
   → Publishes polyarb:arbitrage_found
   → Dashboard updates opportunities table in real-time

3. Optimizer receives polyarb:arbitrage_found
   → Runs Frank-Wolfe optimization
   → Publishes polyarb:optimization_complete

4. Simulator receives polyarb:optimization_complete
   → Validates and executes trades
   → Publishes polyarb:trade_executed (per leg)
   → Publishes polyarb:portfolio_updated

5. Dashboard receives all events
   → Updates via WebSocket to connected browsers`}</CodeBlock>

      <H2>Publishing Events</H2>

      <CodeBlock lang="python">{`# How services publish events
from shared.events import publish, CHANNEL_TRADE_EXECUTED

await publish(redis, CHANNEL_TRADE_EXECUTED, {
    "trade_id": trade.id,
    "opportunity_id": opp.id,
    "market": market.question,
    "side": "BUY",
    "size": 50.0,
})`}</CodeBlock>

      <H2>Subscribing to Events</H2>

      <CodeBlock lang="python">{`# How services subscribe
pubsub = redis.pubsub()
await pubsub.psubscribe("polyarb:*")

async for message in pubsub.listen():
    if message["type"] == "pmessage":
        channel = message["channel"]
        data = json.loads(message["data"])
        await handle_event(channel, data)`}</CodeBlock>

      <Callout type="info">
        The dashboard subscribes to <Code>polyarb:*</Code> (all channels) and broadcasts
        relevant events to connected WebSocket clients for real-time UI updates.
      </Callout>
    </>
  );
}
