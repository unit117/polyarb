import { Suspense, lazy, useMemo, useState } from "react";
import StatsBar from "./components/StatsBar.tsx";
import OpportunitiesTable from "./components/OpportunitiesTable.tsx";
import TradesTable from "./components/TradesTable.tsx";
import PairsTable from "./components/PairsTable.tsx";
import OpportunityDetail from "./components/OpportunityDetail.tsx";

const PnlChart = lazy(() => import("./components/PnlChart.tsx"));
const MetricsPanel = lazy(() => import("./components/MetricsPanel.tsx"));
import { useDashboardData } from "./hooks/useDashboardData.ts";
import type { TradingMode } from "./hooks/useDashboardData.ts";
import s from "./App.module.css";

type Tab = "opportunities" | "trades" | "pairs" | "metrics";

export default function App() {
  const [tab, setTab] = useState<Tab>("opportunities");
  const [selectedOppId, setSelectedOppId] = useState<number | null>(null);
  const {
    stats,
    history,
    baseline,
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

  // Derive selected opportunity from live data so it stays in sync with WS updates
  const selectedOpp = useMemo(
    () => selectedOppId != null ? opportunities.find((o) => o.id === selectedOppId) ?? null : null,
    [selectedOppId, opportunities],
  );

  const liveActive = stats?.live_trading?.active ?? false;

  return (
    <div className={s.root}>
      <header className={s.header}>
        <h1 className={s.title}>PolyArb</h1>
        <span className={s.subtitle}>
          {mode === "paper" ? "Paper Trading" : "Live Trading"} Dashboard
        </span>
        <div className={s.spacer} />
        <a
          href="/docs/"
          className={s.docsLink}
          target="_blank"
          rel="noopener"
        >
          Docs
        </a>
        <ModeSwitcher
          mode={mode}
          onModeChange={setMode}
          liveActive={liveActive}
        />
      </header>

      <StatsBar stats={stats} onStatClick={(t) => setTab(t as Tab)} />
      <Suspense fallback={<div style={{ height: 280, background: "var(--color-bg-panel)", borderRadius: 8, marginBottom: 20 }} />}>
        <PnlChart history={history} baseline={baseline.total_value} />
      </Suspense>

      <nav className={s.tabs}>
        {(["opportunities", "trades", "pairs", "metrics"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`${s.tab} ${tab === t ? s.tabActive : ""}`}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </nav>

      <main className={s.main}>
        {tab === "opportunities" && (
          <OpportunitiesTable
            opportunities={opportunities}
            pagination={opportunitiesPagination}
            onLoadMore={loadMoreOpportunities}
            loading={loadingMore.opportunities}
            onSelect={(o) => setSelectedOppId(o.id)}
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
        {tab === "metrics" && (
          <Suspense fallback={<div style={{ padding: 40, textAlign: "center", color: "var(--color-text-dim)" }}>Loading metrics...</div>}>
            <MetricsPanel />
          </Suspense>
        )}
      </main>

      {selectedOpp && (
        <OpportunityDetail
          opportunity={selectedOpp}
          onClose={() => setSelectedOppId(null)}
        />
      )}
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
    <div className={s.switcher}>
      <button
        className={`${s.switchBtn} ${mode === "paper" ? s.switchBtnActive : ""}`}
        onClick={() => onModeChange("paper")}
      >
        Paper
      </button>
      <button
        className={`${s.switchBtn} ${mode === "live" ? s.switchBtnActiveLive : ""}`}
        onClick={() => onModeChange("live")}
        title={
          liveActive
            ? "Live trading active"
            : "View live trade history"
        }
      >
        Live
        {liveActive && <span className={s.liveDot} />}
      </button>
    </div>
  );
}
