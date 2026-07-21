import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "../hooks.ts";
import { REDIS_CHANNELS } from "../redisChannels.ts";

export type TradingMode = "paper" | "live";

// Re-export types so components can import from one place
export interface Stats {
  active_markets: number;
  market_pairs: number;
  total_opportunities: number;
  total_trades: number;
  portfolio: {
    cash: number;
    total_value: number;
    realized_pnl: number;
    unrealized_pnl: number;
    total_pnl: number;
    total_trades: number;
    settled_trades: number;
    winning_trades: number;
    total_positions: number;
  } | null;
  live_trading?: {
    enabled: boolean;
    active: boolean;
    dry_run: boolean;
  };
}

export interface HistoryPoint {
  timestamp: string;
  cash: number;
  total_value: number;
  realized_pnl: number;
  unrealized_pnl: number;
}

// One leg of the optimizer's arb basket (see shared/schemas/opportunity.py).
export interface TradeLeg {
  market: string; // "A" | "B"
  outcome: string;
  outcome_index?: number;
  side: string; // "BUY" | "SELL"
  edge: number;
  market_price: number;
  fair_price: number;
  venue?: string;
  fee_rate_bps?: number | null;
}

export interface OptimalTrades {
  trades: TradeLeg[];
  estimated_profit: number;
  theoretical_profit: number;
  market_a_prices?: { current: number[]; optimal: number[] };
  market_b_prices?: { current: number[]; optimal: number[] };
}

// The feasibility matrix that defines the logical relation (see shared/schemas/pair.py).
export interface ConstraintMatrix {
  type: string;
  outcomes_a: string[];
  outcomes_b: string[];
  matrix: number[][];
  profit_bound?: number;
  correlation?: string | null;
  implication_direction?: string | null;
  classification_source?: string | null;
}

export interface Opportunity {
  id: number;
  timestamp: string;
  status: string;
  type: string;
  theoretical_profit: number;
  estimated_profit: number;
  fw_iterations: number | null;
  bregman_gap: number | null;
  optimal_trades?: OptimalTrades | null;
  pair: {
    id?: number;
    dependency_type: string;
    confidence: number;
    verified?: boolean;
    implication_direction?: string | null;
    classification_source?: string | null;
    constraint_matrix?: ConstraintMatrix | null;
    resolution_vectors?: unknown;
    market_a: string;
    market_a_venue?: string;
    market_b: string;
    market_b_venue?: string;
  } | null;
}

export interface Trade {
  id: number;
  opportunity_id: number;
  market: string;
  outcome: string;
  side: string;
  size: number;
  entry_price: number;
  vwap_price: number;
  slippage: number;
  fees: number;
  executed_at: string;
  source?: string;
  venue?: string;
}

export interface Pair {
  id: number;
  dependency_type: string;
  confidence: number;
  verified: boolean;
  classification_source?: string | null;
  implication_direction?: string | null;
  correlation?: string | null;
  detected_at: string;
  market_a: { id: number; question: string; venue?: string } | null;
  market_b: { id: number; question: string; venue?: string } | null;
  opportunity_count: number;
}

export interface Position {
  key: string;
  market_id: number;
  outcome: string;
  shares: number; // signed: positive = long, negative = short
  cost_basis: number | null; // total dollar cost basis (magnitude)
  market_question: string | null;
  venue: string | null;
  resolved_outcome: string | null;
  resolved: boolean;
}

export interface PaginationInfo {
  total: number;
  offset: number;
  limit: number;
  hasMore: boolean;
}

export interface Baseline {
  status: "none" | "pending" | "ready";
  total_value: number | null;
  timestamp: string | null;
}

// Pipeline stages, in flow order. Drives event coloring + the header strip.
export type EventStage =
  | "ingest"
  | "detect"
  | "optimize"
  | "simulate"
  | "settle"
  | "portfolio";

// A single event off the Redis bus, as received by the dashboard WS bridge.
// `data` is the raw channel payload (see shared/events.py for shapes).
export interface TapeEvent {
  id: number;
  channel: string;
  kind: string;
  stage: EventStage;
  data: Record<string, unknown>;
  ts: number; // client receive time (epoch ms)
}

export interface Funnel {
  detected: number;
  optimized: number;
  simulated: number;
  traded: number;
}

export interface FunnelData {
  funnel: Funnel;
  status_breakdown: Record<string, number>;
}

export interface DashboardData {
  stats: Stats | null;
  history: HistoryPoint[];
  baseline: Baseline;
  opportunities: Opportunity[];
  trades: Trade[];
  pairs: Pair[];
  positions: Position[];
  funnel: FunnelData | null;
  events: TapeEvent[];
  connected: boolean;
  opportunitiesPagination: PaginationInfo;
  tradesPagination: PaginationInfo;
  pairsPagination: PaginationInfo;
  loadMoreOpportunities: () => void;
  loadMoreTrades: () => void;
  loadMorePairs: () => void;
  loadingMore: { opportunities: boolean; trades: boolean; pairs: boolean };
  mode: TradingMode;
  setMode: (mode: TradingMode) => void;
}

const PAGE_SIZE = 50;
const EVENT_CAP = 400; // ring-buffer size for the live tape
type FetchKey = "stats" | "history" | "baseline" | "opportunities" | "trades" | "pairs" | "funnel" | "positions";

const DEFAULT_REFRESH_KEYS: FetchKey[] = ["stats"];

const CHANNEL_REFRESH_KEYS: Record<string, FetchKey[]> = {
  [REDIS_CHANNELS.ARBITRAGE_FOUND]: ["opportunities", "stats", "funnel"],
  [REDIS_CHANNELS.OPTIMIZATION_COMPLETE]: ["opportunities", "stats", "funnel"],
  [REDIS_CHANNELS.TRADE_EXECUTED]: ["opportunities", "trades", "stats", "history", "funnel"],
  [REDIS_CHANNELS.PORTFOLIO_UPDATED]: ["stats", "history", "baseline", "positions"],
  [REDIS_CHANNELS.PAIR_DETECTED]: ["pairs", "stats"],
  [REDIS_CHANNELS.MARKET_RESOLVED]: ["trades", "stats", "history", "positions"],
};

// Per-channel display metadata for the live tape + pipeline header.
const CHANNEL_EVENT_META: Record<string, { kind: string; stage: EventStage }> = {
  [REDIS_CHANNELS.SNAPSHOT_CREATED]: { kind: "snapshot", stage: "ingest" },
  [REDIS_CHANNELS.MARKET_UPDATED]: { kind: "market_sync", stage: "ingest" },
  [REDIS_CHANNELS.PAIR_DETECTED]: { kind: "pair", stage: "detect" },
  [REDIS_CHANNELS.ARBITRAGE_FOUND]: { kind: "arb", stage: "detect" },
  [REDIS_CHANNELS.OPTIMIZATION_COMPLETE]: { kind: "optimize", stage: "optimize" },
  [REDIS_CHANNELS.TRADE_EXECUTED]: { kind: "trade", stage: "simulate" },
  [REDIS_CHANNELS.CB_TRIPPED]: { kind: "circuit", stage: "simulate" },
  [REDIS_CHANNELS.MARKET_RESOLVED]: { kind: "resolved", stage: "settle" },
};

// Kinds we retain in the ring buffer. Skips portfolio/live_status — those drive
// refetches but aren't interesting as individual tape rows. `snapshot` is kept
// (not shown as a tape row by default) so the Ingest cell can measure throughput.
const STORE_KINDS = new Set(["snapshot", "pair", "arb", "optimize", "trade", "circuit", "resolved"]);

// Kinds the live tape renders as rows (snapshot is throughput-only, not a row).
export const TAPE_KINDS = new Set(["pair", "arb", "optimize", "trade", "circuit", "resolved"]);

function makePagination(total: number, offset: number, limit: number): PaginationInfo {
  return { total, offset, limit, hasMore: offset + limit < total };
}

export function useDashboardData(): DashboardData {
  const [mode, setModeRaw] = useState<TradingMode>("paper");
  const [stats, setStats] = useState<Stats | null>(null);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [baseline, setBaseline] = useState<Baseline>({ status: "pending", total_value: null, timestamp: null });
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [pairs, setPairs] = useState<Pair[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [funnel, setFunnel] = useState<FunnelData | null>(null);
  const [events, setEvents] = useState<TapeEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const nextEventId = useRef(0);

  const [oppPag, setOppPag] = useState<PaginationInfo>({ total: 0, offset: 0, limit: PAGE_SIZE, hasMore: false });
  const [tradesPag, setTradesPag] = useState<PaginationInfo>({ total: 0, offset: 0, limit: PAGE_SIZE, hasMore: false });
  const [pairsPag, setPairsPag] = useState<PaginationInfo>({ total: 0, offset: 0, limit: PAGE_SIZE, hasMore: false });

  const [loadingMore, setLoadingMore] = useState({ opportunities: false, trades: false, pairs: false });
  // Tracks whether the baseline has been resolved (non-null value OR confirmed absent).
  // "resolved" means we got a definitive answer — stop retrying.
  const baselineResolvedRef = useRef(false);
  const modeRef = useRef(mode);

  // Clear mode-dependent data immediately on switch so stale data doesn't flash
  const setMode = useCallback((m: TradingMode) => {
    setModeRaw(m);
    modeRef.current = m;
    setStats(null);
    setHistory([]);
    setBaseline({ status: "pending", total_value: null, timestamp: null });
    baselineResolvedRef.current = false;
    setTrades([]);
    setPositions([]);
    setTradesPag({ total: 0, offset: 0, limit: PAGE_SIZE, hasMore: false });
    loadedCountRef.current.trades = PAGE_SIZE;
  }, []);

  const sourceParam = `source=${mode}`;

  const fetchStats = useCallback(() => {
    const requestMode = mode;
    apiFetch<Stats>(`/stats?${sourceParam}`)
      .then((data) => {
        if (modeRef.current !== requestMode) return;
        setStats(data);
      })
      .catch(console.error);
  }, [sourceParam, mode]);

  const fetchHistory = useCallback(() => {
    const requestMode = mode;
    apiFetch<{ history: HistoryPoint[] }>(`/portfolio/history?hours=24&${sourceParam}`)
      .then((r) => {
        if (modeRef.current !== requestMode) return;
        setHistory(r.history);
      })
      .catch(console.error);
  }, [sourceParam, mode]);

  const fetchBaseline = useCallback(() => {
    // Once resolved (got a value OR confirmed no epoch), stop retrying
    if (baselineResolvedRef.current) return;
    const requestMode = mode;
    apiFetch<Baseline>(`/portfolio/baseline?${sourceParam}`)
      .then((b) => {
        // Discard if mode changed while request was in flight
        if (modeRef.current !== requestMode) return;
        setBaseline(b);
        // "ready" = got a value, "none" = no epoch configured — both are final.
        // "pending" = epoch set but first snapshot not yet written — keep retrying.
        if (b.status === "ready" || b.status === "none") {
          baselineResolvedRef.current = true;
        }
      })
      .catch(console.error);
  }, [sourceParam, mode]);

  // Track how many items are currently loaded so WS refreshes
  // re-fetch the full loaded range, not just the first page.
  // This prevents losing items beyond page 1 (and closing an open detail drawer).
  const loadedCountRef = useRef({ opportunities: PAGE_SIZE, trades: PAGE_SIZE, pairs: PAGE_SIZE });

  const fetchOpportunities = useCallback(() => {
    const limit = loadedCountRef.current.opportunities;
    apiFetch<{ opportunities: Opportunity[]; total: number; offset: number; limit: number }>(`/opportunities?limit=${limit}&offset=0`)
      .then((r) => {
        setOpportunities(r.opportunities);
        setOppPag(makePagination(r.total, 0, limit));
      })
      .catch(console.error);
  }, []);

  const fetchTrades = useCallback(() => {
    const limit = loadedCountRef.current.trades;
    const requestMode = mode;
    apiFetch<{ trades: Trade[]; total: number; offset: number; limit: number }>(`/trades?limit=${limit}&offset=0&${sourceParam}`)
      .then((r) => {
        if (modeRef.current !== requestMode) return;
        setTrades(r.trades);
        setTradesPag(makePagination(r.total, 0, limit));
      })
      .catch(console.error);
  }, [sourceParam, mode]);

  const fetchPairs = useCallback(() => {
    const limit = loadedCountRef.current.pairs;
    apiFetch<{ pairs: Pair[]; total: number; offset: number; limit: number }>(`/pairs?limit=${limit}&offset=0`)
      .then((r) => {
        setPairs(r.pairs);
        setPairsPag(makePagination(r.total, 0, limit));
      })
      .catch(console.error);
  }, []);

  // Funnel is system-wide (counts all opportunities), so it's not source-scoped.
  const fetchFunnel = useCallback(() => {
    apiFetch<FunnelData>(`/metrics/funnel?hours=24`).then(setFunnel).catch(console.error);
  }, []);

  // Open positions for the current source (paper/live).
  const fetchPositions = useCallback(() => {
    const requestMode = mode;
    apiFetch<{ positions: Position[] }>(`/positions?${sourceParam}`)
      .then((r) => {
        if (modeRef.current !== requestMode) return;
        setPositions(r.positions);
      })
      .catch(console.error);
  }, [sourceParam, mode]);

  const loadMoreOpportunities = useCallback(() => {
    const nextOffset = opportunities.length;
    setLoadingMore((prev) => ({ ...prev, opportunities: true }));
    apiFetch<{ opportunities: Opportunity[]; total: number; offset: number; limit: number }>(`/opportunities?limit=${PAGE_SIZE}&offset=${nextOffset}`)
      .then((r) => {
        setOpportunities((prev) => {
          const merged = [...prev, ...r.opportunities];
          loadedCountRef.current.opportunities = merged.length;
          return merged;
        });
        setOppPag(makePagination(r.total, nextOffset, r.limit));
        setLoadingMore((prev) => ({ ...prev, opportunities: false }));
      })
      .catch((e) => {
        console.error(e);
        setLoadingMore((prev) => ({ ...prev, opportunities: false }));
      });
  }, [opportunities.length]);

  const loadMoreTrades = useCallback(() => {
    const nextOffset = trades.length;
    setLoadingMore((prev) => ({ ...prev, trades: true }));
    apiFetch<{ trades: Trade[]; total: number; offset: number; limit: number }>(`/trades?limit=${PAGE_SIZE}&offset=${nextOffset}&${sourceParam}`)
      .then((r) => {
        setTrades((prev) => {
          const merged = [...prev, ...r.trades];
          loadedCountRef.current.trades = merged.length;
          return merged;
        });
        setTradesPag(makePagination(r.total, nextOffset, r.limit));
        setLoadingMore((prev) => ({ ...prev, trades: false }));
      })
      .catch((e) => {
        console.error(e);
        setLoadingMore((prev) => ({ ...prev, trades: false }));
      });
  }, [trades.length, sourceParam]);

  const loadMorePairs = useCallback(() => {
    const nextOffset = pairs.length;
    setLoadingMore((prev) => ({ ...prev, pairs: true }));
    apiFetch<{ pairs: Pair[]; total: number; offset: number; limit: number }>(`/pairs?limit=${PAGE_SIZE}&offset=${nextOffset}`)
      .then((r) => {
        setPairs((prev) => {
          const merged = [...prev, ...r.pairs];
          loadedCountRef.current.pairs = merged.length;
          return merged;
        });
        setPairsPag(makePagination(r.total, nextOffset, r.limit));
        setLoadingMore((prev) => ({ ...prev, pairs: false }));
      })
      .catch((e) => {
        console.error(e);
        setLoadingMore((prev) => ({ ...prev, pairs: false }));
      });
  }, [pairs.length]);

  // Re-fetch everything when mode changes
  useEffect(() => {
    fetchStats();
    fetchHistory();
    fetchBaseline();
    fetchOpportunities();
    fetchTrades();
    fetchPairs();
    fetchFunnel();
    fetchPositions();
  }, [fetchStats, fetchHistory, fetchBaseline, fetchOpportunities, fetchTrades, fetchPairs, fetchFunnel, fetchPositions]);

  // Keep fetch refs current so WebSocket handler always uses latest mode
  const fetchRefsRef = useRef({ fetchStats, fetchHistory, fetchBaseline, fetchOpportunities, fetchTrades, fetchPairs, fetchFunnel, fetchPositions });
  useEffect(() => {
    fetchRefsRef.current = { fetchStats, fetchHistory, fetchBaseline, fetchOpportunities, fetchTrades, fetchPairs, fetchFunnel, fetchPositions };
  }, [fetchStats, fetchHistory, fetchBaseline, fetchOpportunities, fetchTrades, fetchPairs, fetchFunnel, fetchPositions]);

  // Debounced WS fetch — coalesce rapid events into one batch (150ms window)
  const pendingFetches = useRef(new Set<FetchKey>());
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const scheduleFetch = useCallback((...keys: FetchKey[]) => {
    for (const k of keys) pendingFetches.current.add(k);
    clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => {
      const f = fetchRefsRef.current;
      const pending = pendingFetches.current;
      if (pending.has("stats")) f.fetchStats();
      if (pending.has("history")) f.fetchHistory();
      if (pending.has("baseline")) f.fetchBaseline();
      if (pending.has("opportunities")) f.fetchOpportunities();
      if (pending.has("trades")) f.fetchTrades();
      if (pending.has("pairs")) f.fetchPairs();
      if (pending.has("funnel")) f.fetchFunnel();
      if (pending.has("positions")) f.fetchPositions();
      pending.clear();
    }, 150);
  }, []);

  // WebSocket with auto-reconnect — stable effect, doesn't reconnect on mode change
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    let unmounted = false;

    function connect() {
      if (unmounted) return;
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);

      ws.onmessage = (event) => {
        let msg: { channel?: unknown; data?: unknown };
        try {
          msg = JSON.parse(event.data);
        } catch {
          return;
        }
        const channel = typeof msg.channel === "string" ? msg.channel : "";
        if (!channel) return;

        // Buffer interesting events for the live tape + pipeline header rates.
        const meta = CHANNEL_EVENT_META[channel];
        if (meta && STORE_KINDS.has(meta.kind)) {
          const ev: TapeEvent = {
            id: nextEventId.current++,
            channel,
            kind: meta.kind,
            stage: meta.stage,
            data: (msg.data && typeof msg.data === "object" ? msg.data : {}) as Record<string, unknown>,
            ts: Date.now(),
          };
          setEvents((prev) => {
            const next = [ev, ...prev];
            return next.length > EVENT_CAP ? next.slice(0, EVENT_CAP) : next;
          });
        }

        scheduleFetch(...(CHANNEL_REFRESH_KEYS[channel] ?? DEFAULT_REFRESH_KEYS));
      };

      ws.onclose = () => {
        setConnected(false);
        if (!unmounted) {
          reconnectTimer.current = setTimeout(connect, 3000);
        }
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      unmounted = true;
      clearTimeout(reconnectTimer.current);
      clearTimeout(debounceTimer.current);
      wsRef.current?.close();
    };
  }, [scheduleFetch]); // stable — scheduleFetch uses refs internally

  return {
    stats,
    history,
    baseline,
    opportunities,
    trades,
    pairs,
    positions,
    funnel,
    events,
    connected,
    opportunitiesPagination: oppPag,
    tradesPagination: tradesPag,
    pairsPagination: pairsPag,
    loadMoreOpportunities,
    loadMoreTrades,
    loadMorePairs,
    loadingMore,
    mode,
    setMode,
  };
}
