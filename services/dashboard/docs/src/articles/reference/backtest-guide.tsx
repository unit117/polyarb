import { H1, H2, P, Code, CodeBlock, Callout, UL } from "../../components/Prose.tsx";

export default function BacktestGuide() {
  return (
    <>
      <H1>Backtest Guide</H1>

      <P>
        Backtesting runs the PolyArb pipeline against historical data to evaluate strategy
        performance. It uses a separate database (<Code>polyarb_backtest</Code>) populated with
        historical prices.
      </P>

      <H2>Setup</H2>

      <H2>Step 1: Create Backtest Database</H2>

      <P>
        Copy markets and pairs from the live database using dblink:
      </P>

      <CodeBlock lang="bash">{`docker compose run --rm \\
  -e POSTGRES_DB=polyarb_backtest \\
  backtest python -m scripts.backtest_setup`}</CodeBlock>

      <H2>Step 2: Backfill Historical Prices</H2>

      <P>
        Fetch historical price data from the CLOB API:
      </P>

      <CodeBlock lang="bash">{`docker compose run --rm \\
  -e POSTGRES_DB=polyarb_backtest \\
  backtest python -m scripts.backfill_history --max-markets 3000`}</CodeBlock>

      <Callout type="warning">
        The CLOB API rejects history requests for intervals longer than ~14 days. The backfill
        script automatically chunks requests into 14-day windows, but this makes the process
        slow for large date ranges.
      </Callout>

      <H2>Step 3: Run Backtest</H2>

      <CodeBlock lang="bash">{`docker compose run --rm \\
  -e POSTGRES_DB=polyarb_backtest \\
  backtest python -m scripts.backtest --capital 10000`}</CodeBlock>

      <H2>What Gets Simulated</H2>

      <UL>
        <li>Full detection pipeline with historical price snapshots</li>
        <li>Frank-Wolfe optimization on each detected opportunity</li>
        <li>Paper trade execution with VWAP from historical orderbooks</li>
        <li>Portfolio tracking with the same accounting as live</li>
        <li>Settlement when markets resolve</li>
      </UL>

      <H2>Output</H2>

      <P>
        The backtest produces:
      </P>

      <UL>
        <li>Portfolio equity curve (total value over time)</li>
        <li>Trade log with all executions and PnL</li>
        <li>Summary statistics (total return, Sharpe ratio, max drawdown, win rate)</li>
        <li>Per-dependency-type breakdown</li>
      </UL>

      <H2>Limitations</H2>

      <UL>
        <li><strong>Orderbook data</strong> — historical orderbooks may not be available for all periods, falling back to fixed slippage</li>
        <li><strong>Market impact</strong> — backtest assumes your trades don't move the market</li>
        <li><strong>Timing</strong> — backtest processes snapshots sequentially, not at their actual timestamps</li>
        <li><strong>API rate limits</strong> — backfilling many markets takes hours due to CLOB API rate limits</li>
      </UL>
    </>
  );
}
