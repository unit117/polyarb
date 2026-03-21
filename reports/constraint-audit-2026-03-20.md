# PolyArb Constraint Audit Report — 2026-03-20

## Summary

**Status: UNABLE TO AUDIT — DATABASE UNREACHABLE**

The scheduled audit could not connect to the PolyArb PostgreSQL database at `localhost:5434`. The connection was refused, and Docker is not available in the current environment. No checks were performed. This means constraint errors may be going undetected — treat system health as **RED** until the audit can run successfully.

## Connection Details

- **Host:** localhost:5434
- **Error:** `Connection refused — Is the server running on that host and accepting TCP/IP connections?`
- **Docker:** Not installed / not available in this environment

## Recommended Actions

1. **Start the PolyArb services** on the host machine:
   ```bash
   docker compose up -d
   ```
2. **Verify the database is accepting connections:**
   ```bash
   PGPASSWORD=changeme psql -h localhost -p 5434 -U polyarb -d polyarb -c "SELECT count(*) FROM market_pairs;"
   ```
3. **Re-run this audit** once services are confirmed healthy.

## Checks Not Performed

| Check | Description |
|-------|-------------|
| 1 | Low-Confidence LLM Classifications (confidence < 0.75) |
| 2 | Stale Pairs (inactive or expired markets) |
| 3 | Partition Matrix Sanity (price sum ≈ 1.0) |
| 4 | Implication Consistency (A.yes ≤ B.yes) |
| 5 | Optimizer Convergence Issues (max iterations / high Bregman gap) |
| 6 | High-Value Unverified Pairs (theoretical_profit > 0.05) |

---
*Generated automatically by the PolyArb Constraint Auditor — 2026-03-20 (latest run: same day, database still unreachable)*
