import { lazy, type ComponentType } from "react";

export interface Article {
  slug: string;
  title: string;
  category: string;
  component: React.LazyExoticComponent<ComponentType>;
}

export const categories = [
  "Getting Started",
  "Core Concepts",
  "Trading",
  "Risk & Safety",
  "Architecture",
  "Dashboard Guide",
  "Venues",
  "Reference",
];

export const articles: Article[] = [
  // ── Getting Started ──
  { slug: "what-is-polyarb", title: "What is PolyArb?", category: "Getting Started", component: lazy(() => import("./getting-started/what-is-polyarb.tsx")) },
  { slug: "prediction-markets", title: "How Prediction Markets Work", category: "Getting Started", component: lazy(() => import("./getting-started/prediction-markets.tsx")) },
  { slug: "what-is-arbitrage", title: "What is Arbitrage?", category: "Getting Started", component: lazy(() => import("./getting-started/what-is-arbitrage.tsx")) },
  { slug: "dashboard-tour", title: "Quick Tour of the Dashboard", category: "Getting Started", component: lazy(() => import("./getting-started/dashboard-tour.tsx")) },
  { slug: "glossary", title: "Glossary", category: "Getting Started", component: lazy(() => import("./getting-started/glossary.tsx")) },

  // ── Core Concepts ──
  { slug: "market-pairs", title: "Market Pairs & Dependencies", category: "Core Concepts", component: lazy(() => import("./core-concepts/market-pairs.tsx")) },
  { slug: "dependency-types", title: "Dependency Types", category: "Core Concepts", component: lazy(() => import("./core-concepts/dependency-types.tsx")) },
  { slug: "embeddings-pgvector", title: "Embeddings & pgvector", category: "Core Concepts", component: lazy(() => import("./core-concepts/embeddings-pgvector.tsx")) },
  { slug: "detection-pipeline", title: "Arbitrage Detection Pipeline", category: "Core Concepts", component: lazy(() => import("./core-concepts/detection-pipeline.tsx")) },
  { slug: "frank-wolfe", title: "Frank-Wolfe Optimization", category: "Core Concepts", component: lazy(() => import("./core-concepts/frank-wolfe.tsx")) },

  // ── Trading ──
  { slug: "paper-vs-live", title: "Paper vs Live Trading", category: "Trading", component: lazy(() => import("./trading/paper-vs-live.tsx")) },
  { slug: "vwap-execution", title: "VWAP Execution", category: "Trading", component: lazy(() => import("./trading/vwap-execution.tsx")) },
  { slug: "kelly-sizing", title: "Kelly Criterion Sizing", category: "Trading", component: lazy(() => import("./trading/kelly-sizing.tsx")) },
  { slug: "slippage-fees", title: "Slippage & Fees", category: "Trading", component: lazy(() => import("./trading/slippage-fees.tsx")) },
  { slug: "all-or-none", title: "All-or-None Execution", category: "Trading", component: lazy(() => import("./trading/all-or-none.tsx")) },

  // ── Risk & Safety ──
  { slug: "circuit-breakers", title: "Circuit Breakers", category: "Risk & Safety", component: lazy(() => import("./risk-safety/circuit-breakers.tsx")) },
  { slug: "position-limits", title: "Position Limits", category: "Risk & Safety", component: lazy(() => import("./risk-safety/position-limits.tsx")) },
  { slug: "freshness-bounds", title: "Freshness Bounds", category: "Risk & Safety", component: lazy(() => import("./risk-safety/freshness-bounds.tsx")) },
  { slug: "deduplication", title: "Deduplication", category: "Risk & Safety", component: lazy(() => import("./risk-safety/deduplication.tsx")) },
  { slug: "concurrency-guards", title: "Concurrency Guards", category: "Risk & Safety", component: lazy(() => import("./risk-safety/concurrency-guards.tsx")) },

  // ── Architecture ──
  { slug: "service-overview", title: "Service Overview", category: "Architecture", component: lazy(() => import("./architecture/service-overview.tsx")) },
  { slug: "redis-event-bus", title: "Redis Event Bus", category: "Architecture", component: lazy(() => import("./architecture/redis-event-bus.tsx")) },
  { slug: "database-schema", title: "Database Schema", category: "Architecture", component: lazy(() => import("./architecture/database-schema.tsx")) },
  { slug: "websocket-streaming", title: "WebSocket Streaming", category: "Architecture", component: lazy(() => import("./architecture/websocket-streaming.tsx")) },
  { slug: "deployment-nas", title: "Deployment & NAS Setup", category: "Architecture", component: lazy(() => import("./architecture/deployment-nas.tsx")) },

  // ── Dashboard Guide ──
  { slug: "stats-bar", title: "Stats Bar", category: "Dashboard Guide", component: lazy(() => import("./dashboard-guide/stats-bar.tsx")) },
  { slug: "opportunities-table", title: "Opportunities Table", category: "Dashboard Guide", component: lazy(() => import("./dashboard-guide/opportunities-table.tsx")) },
  { slug: "trades-table", title: "Trades Table", category: "Dashboard Guide", component: lazy(() => import("./dashboard-guide/trades-table.tsx")) },
  { slug: "pairs-table", title: "Pairs Table", category: "Dashboard Guide", component: lazy(() => import("./dashboard-guide/pairs-table.tsx")) },
  { slug: "metrics-panel", title: "Metrics Panel", category: "Dashboard Guide", component: lazy(() => import("./dashboard-guide/metrics-panel.tsx")) },
  { slug: "pnl-chart", title: "PnL Chart", category: "Dashboard Guide", component: lazy(() => import("./dashboard-guide/pnl-chart.tsx")) },

  // ── Venues ──
  { slug: "polymarket", title: "Polymarket", category: "Venues", component: lazy(() => import("./venues/polymarket.tsx")) },
  { slug: "kalshi", title: "Kalshi", category: "Venues", component: lazy(() => import("./venues/kalshi.tsx")) },

  // ── Reference ──
  { slug: "configuration", title: "Configuration", category: "Reference", component: lazy(() => import("./reference/configuration.tsx")) },
  { slug: "migrations", title: "Database Migrations", category: "Reference", component: lazy(() => import("./reference/migrations.tsx")) },
  { slug: "backtest-guide", title: "Backtest Guide", category: "Reference", component: lazy(() => import("./reference/backtest-guide.tsx")) },
];
