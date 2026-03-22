import { H1, H2, P, Code, CodeBlock, Table, Callout, UL } from "../../components/Prose.tsx";

export default function CircuitBreakers() {
  return (
    <>
      <H1>Circuit Breakers</H1>

      <P>
        Circuit breakers are safety mechanisms that halt trading when risk thresholds are exceeded.
        They run as pre-trade checks before every execution and can trip on multiple conditions.
      </P>

      <H2>Pre-Trade Checks</H2>

      <P>
        Before every trade execution, the circuit breaker runs five checks in order. If any
        check fails, the trade is blocked.
      </P>

      <Table
        headers={["Check", "Threshold", "Config Key"]}
        rows={[
          ["Kill switch", "Redis key set", <Code>polyarb:kill_switch</Code>],
          ["Daily loss", <Code>$500</Code>, <Code>cb_max_daily_loss</Code>],
          ["Per-market position", <Code>$200</Code>, <Code>cb_max_position_per_market</Code>],
          ["Max drawdown", <Code>10%</Code>, <Code>cb_max_drawdown_pct</Code>],
          ["Consecutive errors", <Code>5</Code>, <Code>cb_max_consecutive_errors</Code>],
        ]}
      />

      <H2>Kill Switch</H2>

      <P>
        The kill switch is a Redis key (<Code>polyarb:kill_switch</Code>) that, when set,
        immediately blocks all trading. This provides an emergency stop that can be activated
        from any service or manually via Redis CLI:
      </P>

      <CodeBlock lang="bash">{`# Emergency stop
redis-cli -p 6380 SET polyarb:kill_switch 1

# Resume trading
redis-cli -p 6380 DEL polyarb:kill_switch`}</CodeBlock>

      <H2>Daily Loss Limit</H2>

      <P>
        Tracks cumulative losses within a 24-hour window. When total losses
        exceed <Code>$500</Code>, all trading halts until the daily counter resets
        (every 86,400 seconds).
      </P>

      <H2>Per-Market Position Limit</H2>

      <P>
        Prevents concentration risk by limiting exposure to any single market
        to <Code>$200</Code>. The check computes post-trade exposure (including the
        proposed trade) and rejects trades that would exceed this limit.
      </P>

      <H2>Max Drawdown</H2>

      <P>
        Computes current drawdown as:
      </P>

      <CodeBlock lang="python">{`drawdown_pct = ((initial_capital - total_value) / initial_capital) * 100.0`}</CodeBlock>

      <P>
        If drawdown exceeds <Code>10%</Code>, all trading stops. This is a hard stop — unlike
        the drawdown scaling in Kelly sizing which gradually reduces position sizes.
      </P>

      <H2>Consecutive Errors</H2>

      <P>
        Tracks consecutive trade execution errors. After <Code>5</Code> consecutive failures,
        trading halts. A single successful trade resets the counter. This catches systemic
        issues like API failures or data problems.
      </P>

      <H2>Cooldown & Reset</H2>

      <UL>
        <li><strong>Cooldown period:</strong> <Code>300 seconds</Code> (5 minutes) after tripping</li>
        <li><strong>Auto-reset:</strong> circuit breaker automatically resets after the cooldown</li>
        <li><strong>Daily reset:</strong> daily loss counter resets every 24 hours</li>
        <li><strong>Success reset:</strong> consecutive error counter resets on any successful trade</li>
      </UL>

      <Callout type="warning">
        When a circuit breaker trips, an event is published
        to <Code>polyarb:circuit_breaker_tripped</Code> with the reason. Monitor the
        dashboard logs for these events.
      </Callout>
    </>
  );
}
