# Knowledge Base — Separate Site at `/docs`

## Context

Build a wiki-style knowledge base as a **separate Vite/React app** served from the dashboard container at `/docs`. Covers everything from prediction market basics to deep system internals. For you and collaborators to learn and reference the system.

## Architecture

```
services/dashboard/
├── web/              ← existing dashboard (served at /)
├── docs/             ← NEW knowledge base app (served at /docs)
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx              ← sidebar + content layout
│       ├── App.module.css
│       ├── index.css
│       ├── glossary.ts          ← shared glossary definitions for tooltips + glossary page
│       ├── components/
│       │   ├── Sidebar.tsx / .module.css
│       │   ├── Prose.tsx / .module.css    ← shared content components
│       │   └── SearchFilter.tsx
│       └── articles/
│           ├── index.ts          ← article registry (slugs, titles, categories, lazy imports)
│           ├── getting-started/
│           │   ├── what-is-polyarb.tsx
│           │   ├── prediction-markets.tsx
│           │   ├── what-is-arbitrage.tsx
│           │   ├── dashboard-tour.tsx
│           │   └── glossary.tsx
│           ├── core-concepts/
│           │   ├── market-pairs.tsx
│           │   ├── dependency-types.tsx
│           │   ├── embeddings-pgvector.tsx
│           │   ├── detection-pipeline.tsx
│           │   └── frank-wolfe.tsx
│           ├── trading/
│           │   ├── paper-vs-live.tsx
│           │   ├── vwap-execution.tsx
│           │   ├── kelly-sizing.tsx
│           │   ├── slippage-fees.tsx
│           │   └── all-or-none.tsx
│           ├── risk-safety/
│           │   ├── circuit-breakers.tsx
│           │   ├── position-limits.tsx
│           │   ├── freshness-bounds.tsx
│           │   ├── deduplication.tsx
│           │   └── concurrency-guards.tsx
│           ├── architecture/
│           │   ├── service-overview.tsx
│           │   ├── redis-event-bus.tsx
│           │   ├── database-schema.tsx
│           │   ├── websocket-streaming.tsx
│           │   └── deployment-nas.tsx
│           ├── dashboard-guide/
│           │   ├── stats-bar.tsx
│           │   ├── opportunities-table.tsx
│           │   ├── trades-table.tsx
│           │   ├── pairs-table.tsx
│           │   ├── metrics-panel.tsx
│           │   └── pnl-chart.tsx
│           ├── venues/
│           │   ├── polymarket.tsx
│           │   └── kalshi.tsx
│           └── reference/
│               ├── configuration.tsx
│               ├── migrations.tsx
│               └── backtest-guide.tsx
└── api/main.py       ← MODIFIED: mount /docs static files
```

## Key Design Decisions

### 1. Separate Vite app (not embedded in dashboard)
- Own `package.json`, `vite.config.ts`, `index.html`
- `base: "/docs/"` in Vite config so all assets resolve correctly
- Reuse the dashboard theme tokens from `services/dashboard/web/src/theme.css` as the source of truth so docs styling does not drift
- If needed for local Vite dev, widen `server.fs.allow` so the docs app can import the sibling theme file cleanly
- Zero impact on dashboard bundle size

### 2. URL search-param routing for deep linking
- `?article=article-slug` drives which article is shown
- Normal `#section-id` anchors are reserved for headings inside an article
- Bookmarkable: `192.168.5.100:8081/docs/?article=vwap-execution#order-book-model`
- Shareable links for collaborators
- No need for React Router — simple `URLSearchParams(window.location.search)` plus `history.pushState`, `popstate`, and `hashchange`

### 3. Article file structure (one file per article)
- Each article is a standalone `.tsx` file exporting a component
- `articles/index.ts` is the registry: `{ slug, title, category, keywords, lastUpdated, component: React.lazy(() => import(...)) }`
- Lazy-loaded via `React.lazy` + `Suspense` — only loads the article you're reading

### 4. Sidebar with search filter
- Categories are collapsible sections
- Text input at top filters articles by title, category, and `keywords`
- Active article highlighted with blue left border
- Independently scrollable (`overflow-y: auto`, full viewport height)

### 5. Prose components (clean article JSX)
- `<Prose.H2>`, `<Prose.H3>` — headings with anchor links
- `<Prose.Code>` — inline code
- `<Prose.CodeBlock lang="python">` — syntax-highlighted blocks (just styled `<pre>`, no dependency), with an optional copy button
- `<Prose.Table>` — styled table matching dark theme
- `<Prose.Callout type="info|warning|tip">` — colored left-border boxes
- `<Prose.Diagram>` — styled `<pre>` for ASCII architecture diagrams
- `<Prose.DashboardLink tab="opportunities">` — cross-links back to dashboard
- `<Prose.ArticlePager>` — previous/next article links for linear reading

### 6. Cross-linking to dashboard
- `<Prose.DashboardLink>` renders links to `/?tab=opportunities` etc.
- Dashboard will read `?tab=` on initial load so docs links can land on the intended tab
- Syncing dashboard tab changes back into the URL is optional follow-up work, not required for v1

### 7. Glossary as first-class feature
- Moved to "Getting Started" category for visibility
- Terms are defined once in `src/glossary.ts`
- Other articles reference glossary entries via `<Prose.Term>` so tooltip text and the glossary page stay in sync

### 8. Content source of truth
- Technical articles must be grounded in the current repo and existing explainer docs, not aspirational architecture
- If a concept is planned but not implemented yet, label it explicitly as future work instead of documenting it as current behavior

### 9. Article metadata
- Each article exposes `lastUpdated` metadata in the registry and the page header displays it under the title
- Search metadata lives in the registry via `keywords`, so jargon and alternate names are searchable without loading every article body
- Registry order is canonical and also drives previous/next navigation

## File Changes

### New files
- `services/dashboard/docs/` — entire new Vite app (~40 files)

### Modified files

**`services/dashboard/Dockerfile`** — Add docs build stage:
```dockerfile
FROM node:22-slim AS docs
WORKDIR /docs
COPY services/dashboard/docs/package.json services/dashboard/docs/package-lock.json* ./
RUN npm install
COPY services/dashboard/docs/ .
RUN npm run build

# In final stage:
COPY --from=docs /docs/dist /app/services/dashboard/docs/dist
```

**`services/dashboard/api/main.py`** — Mount docs before the catch-all:
```python
# Serve Knowledge Base if it exists (must be before "/" catch-all)
docs_dir = Path(__file__).parent.parent / "docs" / "dist"
if docs_dir.exists():
    app.mount("/docs", StaticFiles(directory=str(docs_dir), html=True), name="docs")

# Serve React static build if it exists
static_dir = Path(__file__).parent.parent / "web" / "dist"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
```

**`services/dashboard/web/src/App.tsx`** — Add a "Docs" link in header pointing to `/docs/`, and read `?tab=` on initial load so knowledge-base cross-links can target a specific dashboard tab.

## Layout

```
┌─────────────────────────────────────────────────┐
│  PolyArb Knowledge Base          [← Dashboard]  │  ← header
├──────────┬──────────────────────────────────────┤
│ [Search] │                                      │
│          │  # Article Title                     │
│ Getting  │                                      │
│ Started  │  Content with prose typography,      │
│  > What  │  code blocks, callouts, tables,      │
│  > Pred  │  diagrams, and cross-links.          │
│  > Arb   │                                      │
│  > Tour  │  > Tip: Check the live dashboard     │
│          │  > to see this in action.             │
│ Core     │                                      │
│ Concepts │  ```python                           │
│  > Pairs │  async with SessionFactory() as s:   │
│  > Deps  │      ...                             │
│  ...     │  ```                                 │
│          │                                      │
└──────────┴──────────────────────────────────────┘
  240px           flex: 1 (max-width ~800px)
```

Full viewport height layout: `html, body { height: 100% }`, app is `display: flex; flex-direction: column; height: 100vh`, content area is `display: flex; flex: 1; overflow: hidden`, sidebar and content each `overflow-y: auto`.

## Implementation Order

1. **Scaffold** — Create `docs/` Vite app, `package.json`, `vite.config.ts`, `index.html`, `main.tsx`
2. **Theme + layout** — Reuse dashboard theme tokens, create `App.tsx` + `App.module.css` (sidebar/content split)
3. **Prose + glossary primitives** — `Prose.tsx` + `Prose.module.css` + shared `glossary.ts`
4. **Sidebar + routing** — `Sidebar.tsx` with categories, search, `?article=` routing, and section-anchor support
5. **Article registry** — `articles/index.ts` with lazy imports plus `keywords` and `lastUpdated` metadata
6. **First articles** — Write "Getting Started" category (4 articles + glossary), grounded in current repo behavior
7. **Navigation polish** — Add article header metadata, previous/next links, and optional code-block copy support
8. **Dashboard cross-link support** — Update dashboard `App.tsx` to read `?tab=` on first render
9. **Wire into server** — Update `api/main.py` mount + `Dockerfile` build stage
10. **Build & test docs app locally** — `cd docs && npm run build`, then `npm run dev`
11. **Build & test container-served version** — verify `/docs/` mount and dashboard cross-links through FastAPI
12. **Remaining articles** — Fill in the rest of the article set after the shell and routing are validated
13. **Dashboard header link** — Add "Docs" link in dashboard header
14. **Deploy to NAS** — Standard tar-over-SSH + rebuild

## Verification

1. `cd services/dashboard/docs && npm install && npm run build` — no errors
2. Local dev: `npm run dev` — verify sidebar, search, article rendering, `?article=` routing, and section anchors
3. Search check: search for a jargon term present only in `keywords`, confirm the expected article appears
4. Test deep link: navigate to `localhost:5173/?article=frank-wolfe#duality-gap`, confirm correct article loads and heading scroll works
5. Test article navigation: verify previous/next links move through the registry order correctly
6. Test code-block copy affordance on at least one command/config snippet
7. Test dashboard cross-links: click "← Dashboard" and `DashboardLink` components, confirm `/?tab=pairs` or similar lands on the intended dashboard tab
8. Docker build: full `docker compose build dashboard`
9. Container-served check: verify `/docs/` is served by FastAPI and refresh works on `http://localhost:8081/docs/?article=vwap-execution`
10. Deploy to NAS, verify at `192.168.5.100:8081/docs/`
