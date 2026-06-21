# Development Guide

## Code Quality Standards

### TypeScript/React

- **Strict mode enabled** - All type errors must be resolved
- **No `any` types** - Use proper typing
- **React 19 patterns** - Use latest React features
- **Accessibility** - All interactive elements must be keyboard accessible

### Python

- **Type hints** - Use type annotations for all functions
- **Error handling** - Always handle exceptions gracefully
- **Logging** - Use structured logging for debugging
- **Database transactions** - Always commit/rollback properly

## Architecture Decisions

### Why SQLite?

- **Single-file database** - Easy backup and portability
- **No separate server** - Simplifies deployment
- **WAL mode** - Concurrent reads during writes
- **Sufficient for** - Single-user trading terminal

**Trade-offs:**
- Not suitable for multiple concurrent writers
- Limited to local deployments
- For multi-user, consider PostgreSQL

### Why FastAPI?

- **Modern Python** - Async support, type hints
- **Auto docs** - OpenAPI/Swagger out of the box
- **Fast** - Performance comparable to Node.js
- **Easy testing** - Built-in test client

### Why TanStack Start?

- **Full-stack React** - SSR + client-side routing
- **Type-safe** - End-to-end TypeScript
- **Modern** - Latest React patterns
- **Flexible** - Easy to add features

## Performance Optimization

### Frontend

1. **Code splitting** - Routes are lazy-loaded
2. **Memoization** - Use `useMemo` for expensive calculations
3. **Virtual scrolling** - For large lists (not yet implemented)
4. **Debouncing** - For search inputs

### Backend

1. **Database indexes** - Added for frequently queried columns
2. **Connection pooling** - SQLite WAL mode
3. **Caching** - Price data cached for 30s
4. **Batch operations** - Fetch prices in batches

### Network

1. **Polling interval** - 10s by default (configurable)
2. **Compression** - Enable gzip in production
3. **CDN** - For static assets in production

## Security Best Practices

### Input Validation

```python
# Always validate user input
if pos.size <= 0:
    raise HTTPException(400, "Size must be positive")
```

### SQL Injection Prevention

```python
# Use parameterized queries
conn.execute("SELECT * FROM positions WHERE id = ?", (pos_id,))
```

### API Keys

```python
# Mask API keys in responses
if result.get("api_key"):
    result["api_key"] = result["api_key"][:8] + "..." + result["api_key"][-4:]
```

### CORS Configuration

```python
# Development
ALLOWED_ORIGINS = ["http://localhost:3000"]

# Production
ALLOWED_ORIGINS = [os.getenv("FRONTEND_URL")]
```

## Testing Strategy

### Unit Tests

```python
# server/tests/test_prices.py
def test_fetch_single_price():
    price = prices.fetch_single("AAPL")
    assert price > 0
```

### Integration Tests

```python
# server/tests/test_api.py
def test_create_position():
    response = client.post("/api/positions", json={
        "pair": "AAPL",
        "asset_class": "stock",
        "side": "long",
        "size": 10,
        "confidence": 0.7
    })
    assert response.status_code == 200
```

### E2E Tests

```typescript
// tests/e2e/trading.spec.ts
test('open and close position', async ({ page }) => {
  await page.goto('/');
  await page.click('[data-testid="open-position"]');
  // ...
});
```

## Deployment

### Development

```bash
# Frontend
npm run dev

# Backend
uvicorn main:app --reload
```

### Production

```bash
# Frontend
npm run build
npm run preview

# Backend
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Docker (Not Yet Implemented)

```dockerfile
# Dockerfile.backend
FROM python:3.10-slim
WORKDIR /app
COPY server/requirements.txt .
RUN pip install -r requirements.txt
COPY server/ .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## Monitoring

### Logging

```python
# Backend logging
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.info("Trade executed", extra={"pair": "AAPL", "pnl": 100})
```

### Metrics (Not Yet Implemented)

- Request latency
- Error rates
- Active positions
- P&L over time
- AI provider latency

## Database Migrations

### Manual Schema Updates

```sql
-- Add new column
ALTER TABLE positions ADD COLUMN stop_loss REAL;

-- Add index
CREATE INDEX idx_positions_opened_at ON positions(opened_at);
```

### Backup

```bash
# Backup database
cp server/data/nexus.db server/data/nexus.db.backup

# Restore
cp server/data/nexus.db.backup server/data/nexus.db
```

## API Documentation

### Auto-generated Docs

Visit: `http://localhost:8000/docs`

### Example Requests

```bash
# Get all positions
curl http://localhost:8000/api/positions

# Open position
curl -X POST http://localhost:8000/api/positions \
  -H "Content-Type: application/json" \
  -d '{
    "pair": "AAPL",
    "asset_class": "stock",
    "side": "long",
    "size": 10,
    "confidence": 0.7
  }'

# Get portfolio
curl http://localhost:8000/api/portfolio
```

## Troubleshooting Common Issues

### "Module not found" errors

```bash
# Clear node_modules
rm -rf node_modules package-lock.json
npm install
```

### Python import errors

```bash
# Ensure virtual environment is activated
source .venv/bin/activate  # or .venv\Scripts\activate

# Reinstall dependencies
pip install -r requirements.txt
```

### Database locked

```bash
# Check for zombie processes
ps aux | grep python

# Kill processes
kill -9 <PID>

# Restart backend
```

### CORS errors

1. Check backend is running
2. Verify ALLOWED_ORIGINS in `server/main.py`
3. Check browser console for exact error
4. Ensure credentials are included in fetch requests

## Contributing Guidelines

### Before Submitting PR

1. ✅ Run linter: `npm run lint`
2. ✅ Build succeeds: `npm run build`
3. ✅ Backend starts without errors
4. ✅ Manual testing completed
5. ✅ No console errors
6. ✅ Commit messages are clear

### Code Review Checklist

- [ ] Type safety maintained
- [ ] Error handling implemented
- [ ] Security vulnerabilities addressed
- [ ] Performance considered
- [ ] Documentation updated
- [ ] No breaking changes (or documented)

### Git Workflow

```bash
# Create feature branch
git checkout -b feature/my-feature

# Make changes
git add .
git commit -m "feat: add new feature"

# Push to fork
git push origin feature/my-feature

# Create PR on GitHub
```

## Debugging Tips

### Frontend Debugging

```typescript
// Add breakpoints in browser DevTools
// Or use console.log strategically
console.log('Position data:', position);

// React DevTools
// Install: https://react.dev/learn/react-developer-tools
```

### Backend Debugging

```python
# Add print statements (temporary)
print(f"[DEBUG] Processing position: {pos_id}")

# Or use logging
import logging
logging.debug(f"Position {pos_id} processed")

# Python debugger
import pdb; pdb.set_trace()
```

### Database Debugging

```bash
# Open SQLite CLI
sqlite3 server/data/nexus.db

# List tables
.tables

# Describe table
.schema positions

# Query
SELECT * FROM positions;

# Exit
.quit
```

## Performance Profiling

### Frontend

```typescript
// Use React Profiler
import { Profiler } from 'react';

<Profiler id="Dashboard" onRender={callback}>
  <Dashboard />
</Profiler>
```

### Backend

```python
# Add timing
import time
start = time.time()
# ... code ...
print(f"Took {time.time() - start:.2f}s")
```

## Future Enhancements

### Planned Features

- [ ] WebSocket support for real-time updates
- [ ] Advanced charting with TradingView
- [ ] Backtesting engine
- [ ] Paper trading mode
- [ ] Multi-user support
- [ ] Mobile app
- [ ] Advanced risk management
- [ ] Portfolio optimization
- [ ] Strategy builder

### Technical Debt

- [ ] Add comprehensive test suite
- [ ] Implement proper error boundaries
- [ ] Add database migrations system
- [ ] Implement request throttling
- [ ] Add API versioning
- [ ] Improve error messages
- [ ] Add health check endpoints
- [ ] Implement graceful shutdown

---

**Questions?** Open an issue on GitHub or check the main README.md
