import { H1, H2, H3, P, Code, Table, Callout, Diagram, UL } from "../../components/Prose.tsx";

export default function FrankWolfe() {
  return (
    <>
      <H1>Frank-Wolfe Optimization</H1>

      <P>
        Once an arbitrage opportunity is detected, PolyArb uses the Frank-Wolfe algorithm to
        compute the optimal portfolio that maximizes risk-free profit. This is based on the work
        of Dudik, Lahaie & Pennock (2016, arXiv:1606.02825) on arbitrage-free combinatorial
        market making.
      </P>

      <H2>The Optimization Problem</H2>

      <P>
        Given two markets with prices <Code>p_A</Code> and <Code>p_B</Code>, and a feasibility
        matrix defining which joint outcomes are possible, find a joint probability
        distribution <Code>q</Code> that:
      </P>

      <UL>
        <li>Minimizes KL divergence from market prices: <Code>KL(q || p)</Code></li>
        <li>Satisfies the feasibility constraints (impossible outcomes have zero probability)</li>
        <li>Has valid marginals (each market's probabilities sum to 1)</li>
      </UL>

      <P>
        The gap between the market prices <Code>p</Code> and the optimal feasible
        distribution <Code>q</Code> represents the arbitrage profit.
      </P>

      <H2>Algorithm Steps</H2>

      <Diagram>{`Initialize: q = feasible vertex (deterministic assignment)

For t = 0 to max_iterations:
  1. Compute gradient:  grad = ∇KL(q, p)
  2. Solve IP oracle:   s = argmin⟨grad, s⟩ over feasible set
  3. Compute gap:       gap = ⟨grad, q - s⟩
  4. If gap < tolerance: CONVERGED → break
  5. Step size:         γ = 2 / (t + 2)
  6. Update:            q = (1 - γ)q + γs
  7. Project marginals back to simplex`}</Diagram>

      <H2>Key Parameters</H2>

      <Table
        headers={["Parameter", "Value", "Config Key"]}
        rows={[
          ["Max iterations", <Code>200</Code>, <Code>fw_max_iterations</Code>],
          ["Gap tolerance", <Code>0.001</Code>, <Code>fw_gap_tolerance</Code>],
          ["IP oracle timeout", <Code>5000ms</Code>, <Code>fw_ip_timeout_ms</Code>],
          ["Min edge to trade", <Code>0.03</Code>, <Code>optimizer_min_edge</Code>],
        ]}
      />

      <H2>Convergence</H2>

      <P>
        The algorithm converges when the <strong>duality gap</strong> (also called the
        Bregman gap) drops below <Code>0.001</Code>. The duality gap measures how far the
        current solution is from optimal — a smaller gap means a tighter bound on the
        true profit.
      </P>

      <H3>What If It Doesn't Converge?</H3>

      <P>
        If the algorithm hits 200 iterations without converging, the opportunity is marked
        as <Code>unconverged</Code>. These opportunities may still be traded — the solution
        is suboptimal but often still profitable. The dashboard shows both the iteration count
        and final gap for each opportunity.
      </P>

      <H2>The IP Oracle</H2>

      <P>
        At each iteration, the algorithm needs to find the best feasible vertex — the joint
        outcome assignment that minimizes the gradient inner product. This is solved as an
        integer program (IP) with a 5-second timeout per call. The feasibility matrix defines
        the constraints.
      </P>

      <H2>Output: FWResult</H2>

      <P>
        The optimizer returns a structured result:
      </P>

      <Table
        headers={["Field", "Description"]}
        rows={[
          [<Code>optimal_q</Code>, "Joint probability distribution after projection"],
          [<Code>market_prices</Code>, "Original market prices used"],
          [<Code>iterations</Code>, "Number of iterations actually run"],
          [<Code>final_gap</Code>, "Duality gap at termination"],
          [<Code>converged</Code>, "True if gap < 0.001"],
          [<Code>kl_divergence</Code>, "KL(q || p) at termination"],
        ]}
      />

      <H2>From Optimization to Trades</H2>

      <P>
        After optimization, the <Code>compute_trades()</Code> function converts the optimal
        distribution into concrete trade instructions:
      </P>

      <UL>
        <li>Compare optimal marginals with current market prices</li>
        <li>Determine buy/sell direction for each outcome</li>
        <li>Compute trade sizes based on the distribution gap</li>
        <li>Estimate profit after fees and slippage</li>
      </UL>

      <Callout type="info">
        Conditional pairs are skipped by default (<Code>optimizer_skip_conditional = True</Code>)
        because they tend to have thin margins. The optimizer also skips pairs with unconstrained
        matrices (all 1s) since they offer no arbitrage.
      </Callout>
    </>
  );
}
