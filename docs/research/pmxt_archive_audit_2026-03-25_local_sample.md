# PMXT Archive Audit

- Status: `ok`
- Generated: `2026-03-25T16:21:13.801316Z`

## Access

- Local root: `pmxt_db/polymarket`
- Manifest: `not set`
- HTTP index: `not set`

## Coverage

- File count: `9`
- Oldest visible hour: `2026-02-21T16:00:00Z`
- Newest visible hour: `2026-02-22T00:00:00Z`
- Total known bytes: `5.22 GiB`

## Datasets

### order_book

- Files: `9`
- Oldest hour: `2026-02-21T16:00:00Z`
- Newest hour: `2026-02-22T00:00:00Z`
- Median file size: `673.66 MiB`
- Sample schema columns: `data, market_id, timestamp_created_at, timestamp_received, update_type`
- Distinct market/outcome counts from profiled files:
  - `2026-02-21T16:00:00Z` markets=501 outcomes=None
  - `2026-02-21T20:00:00Z` markets=30462 outcomes=None
  - `2026-02-22T00:00:00Z` markets=30594 outcomes=None

## Joinability

- Status: `insufficient_data`
- Reason: Need both order_book and trades files to evaluate joinability

