# NEXUS API reference

Default base URL: `http://127.0.0.1:8000`

All payloads and responses use JSON. FastAPI validation errors use HTTP 422. Trading rejections usually return:

```json
{
  "detail": {
    "code": "stale_quote",
    "message": "The latest quote is too old to produce a trustworthy fill.",
    "details": {}
  }
}
```

## Read operations

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Backend liveness |
| GET | `/api/system/status` | Database, quote, LLM, and autopilot readiness |
| GET | `/api/bootstrap` | Complete terminal state |
| GET | `/api/portfolio` | Recalculated ledger portfolio |
| GET | `/api/instruments` | Curated instrument catalog and eligibility |
| GET | `/api/quotes?instrument_ids=stock:aapl,crypto:btc-usd` | Standardized quotes |
| GET | `/api/orders` | Audited orders and rejections |
| GET | `/api/positions` | Open positions |
| GET | `/api/trades` | Closed trade ledger |
| GET | `/api/proposals?status=pending` | AI/manual proposals |
| GET | `/api/agent/status` | Agent mode, state, stage, and cycle status |

## Order flow

Preview and order payload:

```json
{
  "instrument_id": "stock:nvda",
  "side": "long",
  "quantity": 1,
  "stop_loss": 218,
  "take_profit": 240,
  "confidence": 0.62,
  "allow_unprotected": false,
  "idempotency_key": "stable-client-generated-key"
}
```

- `POST /api/orders/preview`: returns `allowed`, estimated fill, notional, modeled loss to stop, fees, slippage, resulting exposure, errors, and warnings.
- `POST /api/orders`: fills or returns a structured rejection. Always preview first.
- `POST /api/positions/{id}/close`: closes at a fresh eligible paper quote.
- `PATCH /api/positions/{id}/protection`: body `{ "stop_loss": 218, "take_profit": 240 }`.

## Proposal flow

- `POST /api/agent/trigger`: starts one advisory/autopilot cycle; returns immediately.
- Poll `GET /api/agent/status` until `cycle_active` is false.
- `POST /api/proposals/{id}/approve`: routes the proposal through deterministic execution.
- `POST /api/proposals/{id}/reject`: body `{ "reason": "Concise reason" }`.

## Controls

- `PUT /api/agent/config`: body may include `mode` (`advisory` or `guarded_autopilot`), `risk_profile`, `allowed_asset_classes`, or `interval_seconds`.
- `POST /api/agent/kill-switch`: body `{ "enabled": true }`.
- The kill switch blocks new entries, approvals, and agent cycles but protective monitoring remains active.
- `POST /api/agent/start` enables recurring cycles. Avoid unless explicitly requested.
- `POST /api/agent/stop` stops recurring cycles.

## Important fields

- Instrument eligibility: `trade_enabled` or `research_only`.
- Quote safety: `as_of`, `source`, `delayed`, `stale`, `market_status`.
- Position safety: `protection_status`, `stop_loss`, `take_profit`, `quote_stale`.
- Proposal state: `pending`, `executed`, or `rejected`.
- Legacy idea review state: `scored`, `unscored`, `invalid`, `stale`, or `needs_review`.
