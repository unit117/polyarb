export const REDIS_CHANNELS = {
  MARKET_UPDATED: "polyarb:market_updated",
  SNAPSHOT_CREATED: "polyarb:snapshot_created",
  PAIR_DETECTED: "polyarb:pair_detected",
  ARBITRAGE_FOUND: "polyarb:arbitrage_found",
  OPTIMIZATION_COMPLETE: "polyarb:optimization_complete",
  TRADE_EXECUTED: "polyarb:trade_executed",
  PORTFOLIO_UPDATED: "polyarb:portfolio_updated",
  MARKET_RESOLVED: "polyarb:market_resolved",
  LIVE_STATUS: "polyarb:live_status",
  CB_TRIPPED: "polyarb:cb_tripped",
} as const;
