import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "../hooks.ts";

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
  total_value: number;
  realized_pnl: number;
  unrealized_pnl: number;
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
  pair: {
    dependency_type: string;
    confidence: number;
    market_a: string;
    market_b: string;
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
}

export interface Pair {
  id: number;
  dependency_type: string;
  confidence: number;
  verified: boolean;
  detected_at: string;
  market_a: { id: number; question: string } | null;
  market_b: { id: number; question: string } | null;
  opportunity_count: number;
}

export interface PaginationInfo {
  total: number;
  offset: number;
  limit: number;
  hasMore: boolean;
}

export interface DashboardData {
  stats: Stats | null;
  history: HistoryPoint[];
  opportunities: Opportunity[];
  trades: Trade[];
  pairs: Pair[];
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

const PAGE_SIZE = 200;

function makePagination(total: number, offset: number, limit: number): PaginationInfo {
  return { total, offset, limit, hasMore: offset + limit < total };
}

export function useDashboardData(): DashboardData {
  const [mode, setModeRaw] = useState<TradingMode>("paper");
  const [stats, setStats] = useState<Stats | null>(null);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [pairs, setPairs] = useState<Pair[]>([]);

  const [oppPag, setOppPag] = useState<PaginationInfo>({ total: 0, offset: 0, limit: PAGE_SIZE, hasMore: false });
  const [tradesPag, setTradesPag] = useState<PaginationInfo>({ total: 0, offset: 0, limit: PAGE_SIZE, hasMore: false });
  const [pairsPag, setPairsPag] = useState<PaginationInfo>({ total: 0, offset: 0, limit: PAGE_SIZE, hasMore: false });

  const [loadingMore, setLoadingMore] = useState({ opportunities: false, trades: false, pairs: false });

  // Clear mode-dependent data immediately on switch so stale data doesn't flash
  const setMode = useCallback((m: TradingMode) => {
    setModeRaw(m);
    setStats(null);
    setHistory([]);
    setTrades([]);
    setTradesPag({ total: 0, offset: 0, limit: PAGE_SIZE, hasMore: false });
  }, []);

  const sourceParam = `source=${mode}`;

  const fetchStats = useCallback(() => {
    apiFetch<Stats>(`/stats?${sourceParam}`).then(setStats).catch(console.error);
  }, [sourceParam]);

  const fetchHistory = useCallback(() => {
    apiFetch<{ history: HistoryPoint[] }>(`/portfolio/history?hours=24&${sourceParam}`)
      .then((r) => setHistory(r.history))
      .catch(console.error);
  }, [sourceParam]);

  const fetchOpportunities = useCallback(() => {
    apiFetch<{ opportunities: Opportunity[]; total: number; offset: number; limit: number }>(`/opportunities?limit=${PAGE_SIZE}&offset=0`)
      .then((r) => {
        setOpportunities(r.opportunities);
        setOppPag(makePagination(r.total, r.offset, r.limit));
      })
      .catch(console.error);
  }, []);

  const fetchTrades = useCallback(() => {
    apiFetch<{ trades: Trade[]; total: number; offset: number; limit: number }>(`/trades?limit=${PAGE_SIZE}&offset=0&${sourceParam}`)
      .then((r) => {
        setTrades(r.trades);
        setTradesPag(makePagination(r.total, r.offset, r.limit));
      })
      .catch(console.error);
  }, [sourceParam]);

  const fetchPairs = useCallback(() => {
    apiFetch<{ pairs: Pair[]; total: number; offset: number; limit: number }>(`/pairs?limit=${PAGE_SIZE}&offset=0`)
      .then((r) => {
        setPairs(r.pairs);
        setPairsPag(makePagination(r.total, r.offset, r.limit));
      })
      .catch(console.error);
  }, []);

  const loadMoreOpportunities = useCallback(() => {
    const nextOffset = opportunities.length;
    setLoadingMore((prev) => ({ ...prev, opportunities: true }));
    apiFetch<{ opportunities: Opportunity[]; total: number; offset: number; limit: number }>(`/opportunities?limit=${PAGE_SIZE}&offset=${nextOffset}`)
      .then((r) => {
        setOpportunities((prev) => [...prev, ...r.opportunities]);
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
        setTrades((prev) => [...prev, ...r.trades]);
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
        setPairs((prev) => [...prev, ...r.pairs]);
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
    fetchOpportunities();
    fetchTrades();
    fetchPairs();
  }, [fetchStats, fetchHistory, fetchOpportunities, fetchTrades, fetchPairs]);

  // Keep fetch refs current so WebSocket handler always uses latest mode
  const fetchRefsRef = useRef({ fetchStats, fetchHistory, fetchOpportunities, fetchTrades, fetchPairs });
  useEffect(() => {
    fetchRefsRef.current = { fetchStats, fetchHistory, fetchOpportunities, fetchTrades, fetchPairs };
  }, [fetchStats, fetchHistory, fetchOpportunities, fetchTrades, fetchPairs]);

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

      ws.onmessage = (event) => {
        let channel: string;
        try {
          const msg = JSON.parse(event.data);
          channel = typeof msg.channel === "string" ? msg.channel : "";
        } catch {
          return;
        }

        const f = fetchRefsRef.current;
        if (channel.startsWith("polyarb:opportunity:")) {
          f.fetchOpportunities();
          f.fetchStats();
        } else if (channel.startsWith("polyarb:trade:")) {
          f.fetchTrades();
          f.fetchStats();
          f.fetchHistory();
        } else if (channel.startsWith("polyarb:pair:")) {
          f.fetchPairs();
          f.fetchStats();
        } else {
          f.fetchStats();
        }
      };

      ws.onclose = () => {
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
      wsRef.current?.close();
    };
  }, []); // stable — no deps, uses refs for latest fetch functions

  return {
    stats,
    history,
    opportunities,
    trades,
    pairs,
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
