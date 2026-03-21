import { useState } from "react";
import StatsBar from "./components/StatsBar.tsx";
import OpportunitiesTable from "./components/OpportunitiesTable.tsx";
import TradesTable from "./components/TradesTable.tsx";
import PnlChart from "./components/PnlChart.tsx";
import PairsTable from "./components/PairsTable.tsx";
import { useDashboardData } from "./hooks/useDashboardData.ts";
import type { TradingMode } from "./hooks/useDashboardData.ts";

type Tab = "opportunities" | "trades" | "pairs";

export default function App() {
  const [tab, setTab] = useState<Tab>("opportunities");
  const {
    stats,
    history,
    opportunities,
    trades,
    pairs,
    opportunitiesPagination,
    tradesPagination,
    pairsPagination,
    loadMoreOpportunities,
    loadMoreTrades,
    loadMorePairs,
    loadingMore,
    mode,
    setMode,
  } = useDashboardData();

  const liveActive = stats?.live_trading?.active ?? false;

  return (
    <div style={styles.root}>
      <header style={styles.header}>
        <h1 style={styles.title}>PolyArb</h1>
        <span style={styles.subtitle}>
          {mode === "paper" ? "Paper Trading" : "Live Trading"} Dashboard
        </span>
        <div style={styles.spacer} />
        <ModeSwitcher
          mode={mode}
          onModeChange={setMode}
          liveActive={liveActive}
        />
      </header>

      <StatsBar stats={stats} onStatClick={(t) => setTab(t as Tab)} />
      <PnlChart history={history} />

      <nav style={styles.tabs}>
        {(["opportunities", "trades", "pairs"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              ...styles.tab,
              ...(tab === t ? styles.tabActive : {}),
            }}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </nav>

      <main style={styles.main}>
        {tab === "opportunities" && (
          <OpportunitiesTable
            opportunities={opportunities}
            pagination={opportunitiesPagination}
            onLoadMore={loadMoreOpportunities}
            loading={loadingMore.opportunities}
          />
        )}
        {tab === "trades" && (
          <TradesTable
            trades={trades}
            pagination={tradesPagination}
            onLoadMore={loadMoreTrades}
            loading={loadingMore.trades}
          />
        )}
        {tab === "pairs" && (
          <PairsTable
            pairs={pairs}
            pagination={pairsPagination}
            onLoadMore={loadMorePairs}
            loading={loadingMore.pairs}
          />
        )}
      </main>
    </div>
  );
}

function ModeSwitcher({
  mode,
  onModeChange,
  liveActive,
}: {
  mode: TradingMode;
  onModeChange: (m: TradingMode) => void;
  liveActive: boolean;
}) {
  return (
    <div style={switcherStyles.container}>
      <button
        style={{
          ...switcherStyles.btn,
          ...(mode === "paper" ? switcherStyles.btnActive : {}),
        }}
        onClick={() => onModeChange("paper")}
      >
        Paper
      </button>
      <button
        style={{
          ...switcherStyles.btn,
          ...(mode === "live" ? switcherStyles.btnActiveLive : {}),
        }}
        onClick={() => onModeChange("live")}
        title={
          liveActive
            ? "Live trading active"
            : "View live trade history"
        }
      >
        Live
        {liveActive && <span style={switcherStyles.dot} />}
      </button>
    </div>
  );
}

const switcherStyles: Record<string, React.CSSProperties> = {
  container: {
    display: "flex",
    gap: 2,
    background: "#111118",
    borderRadius: 6,
    padding: 2,
  },
  btn: {
    padding: "6px 16px",
    background: "transparent",
    border: "none",
    borderRadius: 4,
    color: "#666",
    cursor: "pointer",
    fontSize: 13,
    fontWeight: 500,
    position: "relative",
  },
  btnActive: {
    background: "#1a2e1a",
    color: "#00ff88",
  },
  btnActiveLive: {
    background: "#2e1a1a",
    color: "#ff6644",
  },
  dot: {
    display: "inline-block",
    width: 6,
    height: 6,
    borderRadius: "50%",
    background: "#00ff88",
    marginLeft: 6,
    verticalAlign: "middle",
  },
};

const styles: Record<string, React.CSSProperties> = {
  root: {
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace',
    background: "#0a0a0f",
    color: "#e0e0e0",
    minHeight: "100vh",
    padding: "20px 32px",
  },
  header: {
    display: "flex",
    alignItems: "baseline",
    gap: 12,
    marginBottom: 24,
  },
  title: { margin: 0, fontSize: 28, color: "#00ff88" },
  subtitle: { fontSize: 14, color: "#666" },
  spacer: { flex: 1 },
  tabs: {
    display: "flex",
    gap: 4,
    marginBottom: 16,
    borderBottom: "1px solid #222",
    paddingBottom: 8,
  },
  tab: {
    padding: "8px 20px",
    background: "transparent",
    border: "1px solid #333",
    borderRadius: 6,
    color: "#999",
    cursor: "pointer",
    fontSize: 13,
  },
  tabActive: {
    background: "#1a1a2e",
    color: "#00ff88",
    borderColor: "#00ff88",
  },
  main: {},
};
