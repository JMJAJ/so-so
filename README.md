# NEXUS - AI Trading Terminal

Autonomous AI trading terminal with live forex, stock, crypto, and futures positions tracking.

## 🚀 Quick Start

### Prerequisites

- **Node.js** 18+ or **Bun**
- **Python** 3.10+
- **Ollama** (optional, for local AI) or API keys for other providers

### Installation

#### 1. Frontend Setup

```bash
# Install dependencies
npm install
# or
bun install

# Copy environment template
cp .env.example .env

# Edit .env and add your Supabase credentials
```

#### 2. Backend Setup

```bash
cd server

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Running the Application

On Windows, start the backend and frontend together:

```powershell
.\start-nexus.ps1
```

The launcher uses `server/.venv` when available, keeps backend logs in the Windows temporary directory, and shuts the backend down when the frontend exits.

For separate terminals:

#### Terminal 1: Start Python Backend

```bash
cd server
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Backend will be available at: `http://localhost:8000`
API docs: `http://localhost:8000/docs`

#### Terminal 2: Start Frontend

```bash
npm run dev
# or
bun run dev
```

Frontend will be available at: `http://localhost:3000`

## 🔧 Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure:

```env
# Supabase (required for authentication)
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
```

### AI Provider Setup

The application supports multiple AI providers:

1. **Ollama (Local)** - No API key needed
   - Install: https://ollama.ai
   - Pull model: `ollama pull minimax-m3:cloud`
   - Start: `ollama serve`

2. **OpenAI** - Requires API key
3. **Anthropic (Claude)** - Requires API key
4. **Google Gemini** - Requires API key
5. **OpenRouter** - Requires API key
6. **Groq** - Free tier available
7. **DeepSeek** - Requires API key
8. **LM Studio** - Local, no API key needed

Configure AI provider in the Settings panel after starting the app.

## 📁 Project Structure

```
.
├── src/                    # Frontend (React + TanStack)
│   ├── routes/            # Application routes
│   ├── components/        # UI components
│   └── integrations/      # Supabase integration
├── server/                # Backend (Python FastAPI)
│   ├── main.py           # API endpoints
│   ├── agent.py          # AI trading agent
│   ├── db.py             # Database layer
│   ├── llm.py            # Multi-provider LLM abstraction
│   ├── prices.py         # Market data fetcher
│   └── context.py        # Technical analysis
└── supabase/             # Database migrations
```

## 🔒 Security Notes

### Development vs Production

**Current CORS settings are for DEVELOPMENT only:**

```python
# server/main.py
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
]
```

**For production:**
1. Update `ALLOWED_ORIGINS` to your production domain
2. Use environment variables for API keys (not database storage)
3. Enable HTTPS
4. Add rate limiting middleware
5. Implement proper authentication

### API Keys

⚠️ **Warning:** API keys are currently stored in SQLite without encryption.

**Recommendations:**
- Use environment variables for sensitive keys
- Consider using a key vault service
- Never commit `.env` files to version control

## 🧪 Testing

```bash
# Frontend
npm run lint
npm run build

# Backend
cd server
python -m pytest  # (when tests are added)
```

## 📊 Features

- **Paper Execution:** Audited, preview-first paper orders with modeled friction
- **Guarded AI:** Advisory and guarded-autopilot modes; every proposal passes deterministic risk checks
- **Risk Controls:** Fixed conservative, balanced, and aggressive presets plus a kill switch
- **Data Honesty:** Quote freshness, delayed/proxy labeling, and accuracy-gated derivatives
- **Ledger Migration:** Existing SQLite history is backed up and preserved without invented outcomes
- **Technical Analysis:** Built-in indicators (RSI, MACD, Bollinger Bands, etc.)
- **Trade Ideas:** AI-generated trade setups with entry/SL/TP levels
- **Chart Annotations:** Draw support/resistance, trendlines, zones
- **Risk Management:** Configurable risk profiles (conservative, moderate, aggressive)
- **Multi-Asset Support:** Forex, stocks, crypto, CFDs, futures
- **Portfolio Analytics:** P&L tracking, win rate, profit factor, equity curve

## Operating Boundary

NEXUS is a local, single-user paper-trading and research terminal. It does not connect to a brokerage or place real-money orders. The free yfinance feed can be delayed and is explicitly labeled as such; stale or research-only quotes cannot create paper fills.

## 📝 Development Notes

### Database Schema

SQLite database located at: `server/data/nexus.db`

Tables:
- `positions` - Open positions
- `trades` - Closed trades
- `logs` - AI decision log
- `trade_ideas` - Generated trade setups
- `annotations` - Chart annotations
- `portfolio_config` - Portfolio settings
- `llm_config` - AI provider configuration

### Adding New Asset Classes

1. Add to `WATCHLIST` in `server/agent.py`
2. Update `is_market_open()` function if needed
3. Add market hours logic

### Extending AI Capabilities

Edit prompts in `server/agent.py`:
- `_BASE_PROMPT` - Core trading rules
- `_PROFILE_*` - Risk profile behaviors
- `_OUTPUT_FORMAT` - Response structure

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📄 License

[Your License Here]

## ⚠️ Disclaimer

**This is educational software for learning purposes.**

- NOT financial advice
- NO guarantee of profitability
- Trading involves substantial risk
- Past performance ≠ future results
- Use at your own risk
- Always test with paper trading first

## 🆘 Troubleshooting

### Backend won't start

```bash
# Check Python version
python --version  # Should be 3.10+

# Check if port 8000 is available
lsof -i :8000  # macOS/Linux
netstat -ano | findstr :8000  # Windows

# Reinstall dependencies
cd server
pip install -r requirements.txt --force-reinstall
```

### Frontend can't connect to backend

1. Ensure backend is running on port 8000
2. Check browser console for CORS errors
3. Verify proxy configuration in `vite.config.ts`
4. Try: `curl http://localhost:8000/api/health`

### AI agent not working

1. Check AI provider is running (e.g., Ollama)
2. Verify API keys in Settings
3. Check backend logs for errors
4. Test provider: `curl http://localhost:11434/api/tags` (Ollama)

### Database errors

```bash
# Reset database (⚠️ deletes all data)
rm server/data/nexus.db
# Restart backend to recreate
```

## 📚 Resources

- [TanStack Start Docs](https://tanstack.com/start)
- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [Ollama Docs](https://github.com/ollama/ollama)
- [yfinance Docs](https://pypi.org/project/yfinance/)

---

**Built with:** React 19, TanStack Start, FastAPI, SQLite, Tailwind CSS, shadcn/ui
