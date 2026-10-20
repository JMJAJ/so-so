# NEXUS // Evidence-based investment research

## Project Overview
A local research terminal whose AI recommends 1–8 week investments. The recommendations are
grounded in market history, structured event history (earnings, Fed, macro surprises, market
shocks, GDELT geopolitics) and classified news, and every call is verified with paper trading.
The frontend is TanStack Start (React 19). The backend is a Python FastAPI package, `server/nexus/`.

## Architecture
- **Frontend**: TanStack Start (React 19) + Tailwind CSS v4 + Vite, data via React Query.
- **Backend**: `server/nexus/` package served by `server/main.py` (`uvicorn main:app`, port 8000).
- **Database**: SQLite at `server/data/nexus_v3.db` (WAL). The old v2 `nexus.db` is untouched and unused.
- **Data**: yfinance (daily bars, earnings), FRED `fredgraph.csv` (keyless), GDELT 1.0 daily
  exports (aggregated into theme counts) and the GDELT DOC API, plus RSS/Yahoo/Finnhub headlines.
- **AI**: pluggable providers in `nexus/llm/` (Anthropic SDK; OpenAI-compatible for OpenAI,
  OpenRouter, Ollama, LM Studio) with tool calling. The analyst, chat and CLI share `agent/tools.py`.
- **Scheduler**: APScheduler in-process (`nexus/jobs.py`).

## Key Files
| File | Purpose |
|------|---------|
| `server/nexus/db.py` | Schema and query helpers |
| `server/nexus/universe.py` | ~150 instruments, ids like `stock:aapl`, `etf:spy`, `crypto:btc`, `forex:eurusd`, `commodity:gold`, `index:vix` |
| `server/nexus/taxonomy.py` | Event types (with history) and news categories, plus how each category maps to them |
| `server/nexus/ingest/*` | prices/quotes, FRED macro, event detection, GDELT, headlines |
| `server/nexus/research/features.py` | Point-in-time technicals and market regime |
| `server/nexus/research/event_study.py` | Per (event type × asset) forward abnormal returns, edge, hit rate, t-stat |
| `server/nexus/research/analogs.py` | Nearest-neighbour historical states and forward paths |
| `server/nexus/research/correlation.py` | Peers and lead-lag drivers |
| `server/nexus/research/signals.py` | Signal panel (shared by backtest and live) and model application |
| `server/nexus/research/backtest.py` | Walk-forward validation per asset class, with point-in-time signal selection |
| `server/nexus/agent/{tools,loop,analyst,chat}.py` | Tool registry, provider-neutral tool loop, daily analyst, chat |
| `server/nexus/paper.py` | Paper broker: sizing, fills, stops/targets/expiry, portfolio |
| `server/nexus/recommendations.py` | Recommendation lifecycle, scoring, track record, lessons |
| `server/nexus/api.py` | All HTTP routes (chat is SSE) |
| `server/nexus/cli.py` | `python -m nexus …` |
| `src/features/*` | One folder per view, plus `shell/` (layout and UI primitives), `charts/`, `chat/`, `recs/` |
| `src/lib/{api,types,format,nav}.ts(x)` | API client (`fetchJson`, `streamChat`), types, formatters, view navigation |

## Development
```bash
npm install && npm run dev                       # frontend on :3000
cd server && pip install -r requirements.txt
python -m uvicorn main:app --port 8000           # backend
python -m pytest tests                           # backend tests (offline, synthetic data)
npm run typecheck && npm run lint                # frontend checks
```

## Conventions
- **Point-in-time or it doesn't ship.** Any feature or signal at date t may use data ≤ t only.
  Event dates are the first session the market could react. Tests in
  `server/tests/test_research.py` guard this.
- **Every claim needs n and a t-stat.** Tools return raw statistics; the UI shows reliability
  badges. Don't present a signal as an edge unless walk-forward says so.
- **Styling**: Tailwind v4 with the semantic tokens in `src/styles.css` (`bull`, `bear`,
  `primary`, `muted-foreground`), the `terminal-panel` utility, uppercase wide-tracked labels.
  Use the primitives in `src/features/shell/ui.tsx`.
- **Data fetching**: React Query hooks calling `api.*` from `src/lib/api.ts`. Navigation is
  `useNav()` (`?v=view&id=…` in the URL).
- **Asset classes**: `stock | etf | crypto | forex | commodity | index`; `index` is research-only.

## Important Notes
- SSR is disabled on the index route (`ssr: false`).
- `vite.config.ts` uses a shared TanStack config package. Do NOT manually add `tanstackStart`,
  `viteReact`, `tailwindcss`, `tsConfigPaths` or `nitro`.
- `routeTree.gen.ts` is auto-generated. Do not edit it.
- API keys entered in Settings are AES-encrypted in SQLite using `server/data/.secret`. Environment
  variables win over stored keys.
