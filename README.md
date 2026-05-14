# Trading Agent

A small personal app that suggests **day trades across NIFTY 100 stocks** by reading the news, looking at each stock's recent price action, and combining the two into a short, opinionated call: "go long here, stop here, target here, and here's why."

It runs a few small background workers ("agents") that quietly collect data while you do other things, and a barebones dashboard you can pull up on your phone or laptop to see today's top picks.

> Heads up: this is a personal tool, not investing advice. The model can be wrong. Treat every suggestion as a starting point, not a signal to click buy.

## What it actually does

Three things happen on a loop, in the background:

1. **A news agent** pulls the latest financial headlines from CNBC TV18, Economic Times, LiveMint, Hindu BusinessLine, and Investing.com India via their RSS feeds and stores them in a small local database. ~700 fresh articles per day.
2. **A market agent** downloads the last six months of daily prices for **the full NIFTY 100 universe** (~100 large/mid-cap NSE stocks) plus the NIFTY 50 and SENSEX indices for macro context, all from Yahoo Finance.
3. **A signal + LLM agent** runs every hour:
   - First, a plain rule engine runs across every stock and computes a few classic technical indicators (RSI, MACD, 20/50 moving averages, ATR), using a weighted vote across them where the SMA20-vs-SMA50 trend signal carries the heaviest weight. Each stock that gets a clear directional vote becomes a *candidate* with an entry, stop, and target derived from volatility.
   - Then it hands the top ~25 candidates plus the recent news headlines to **an LLM** (Gemini 2.5 Flash by default) and asks it to act as a disciplined analyst: match news to specific stocks by company name, drop calls where news contradicts the technicals, rank what's left, and write a one-sentence rationale per pick. The LLM returns the **top 10 trades** — that's what you see on the dashboard.

The dashboard itself is intentionally barebones — a single page listing the day's top suggestions as cards with the ticker + company name, direction (LONG/SHORT), entry/stop/target, a confidence percentage, the rationale, the technical signals that fired, and links to the news articles that drove the call.

## How we built it (in plain language)

Think of the architecture as a four-stage assembly line:

```
  News RSS ──┐
             ├──▶ SQLite ──▶ Rule engine ──▶ LLM (Gemini) ──▶ Top 10 trades ──▶ UI
  yfinance ──┘                (per-stock     (matches news
                               candidates,   to tickers,
                               ~100 stocks)  ranks, drops)
```

- **Why rules first, then an LLM?** Pure LLM-generated trade ideas can be confidently wrong and expensive (every refresh would be a fresh, long prompt over 100 tickers). Pure rule-based ideas don't know about the news. So we let cheap, deterministic rules surface a list of candidates — "these stocks have a recognisable setup right now" — and only then ask the LLM to apply judgement: weigh the news, drop bad ideas, pick the top 10, and explain each call. Best of both worlds, and the LLM bill stays small.

- **Why provider-agnostic on the LLM?** The codebase uses the `openai` SDK with a configurable `base_url`, so you can point it at Gemini, Groq, DeepSeek, OpenAI, or local Ollama by changing two env vars. Gemini 2.5 Flash is the default because its quality/cost ratio for this task is hard to beat (~5¢/month).

- **Why a scheduler?** You shouldn't have to babysit this. APScheduler runs each agent on its own interval — news every 30 minutes, prices every 15, the suggestion pipeline every 60. The first run also fires on app startup so the UI isn't empty.

- **Why FastAPI?** It's the simplest way to expose a tiny REST API in Python, plays well with background workers, and gives you free interactive docs at `/docs` for poking at the endpoints.

- **Why SQLite?** Zero setup, one file, perfectly fine for a single-user app. The schema has three tables: news articles, price bars, and trade suggestions. If you ever outgrow it, swap the `DATABASE_URL` to Postgres — nothing else needs to change.

- **Why React?** Honestly, just to keep it simple. One page, a few cards, no framework heroics. Vite proxies `/api` calls to the FastAPI backend in dev.

## Project structure

```
trading-agent/
├── backend/
│   ├── app/
│   │   ├── main.py            FastAPI app + lifespan starts the scheduler
│   │   ├── config.py          Env-driven settings
│   │   ├── db.py              SQLAlchemy engine + session
│   │   ├── models.py          NewsArticle / MarketBar / TradeSuggestion tables
│   │   ├── scheduler.py       APScheduler job wiring
│   │   ├── universe.py        NIFTY 100 ticker list with company names
│   │   ├── agents/
│   │   │   ├── news_agent.py     RSS fetcher
│   │   │   ├── market_agent.py   yfinance OHLCV fetcher (all 100 stocks)
│   │   │   ├── signal_agent.py   Weighted RSI / MACD / SMA / ATR per stock
│   │   │   └── llm_agent.py      Calls the LLM to rank + explain top picks
│   │   └── routes/
│   │       ├── trades.py      GET /api/trades, POST /api/refresh
│   │       └── news.py        GET /api/news
│   ├── requirements.txt
│   └── .env.example
└── frontend/
    ├── src/
    │   ├── App.tsx            The one page
    │   ├── api.ts             Tiny fetch wrappers
    │   └── styles.css
    ├── index.html
    └── package.json
```

## Running it locally

You need Python 3.11+ and Node 18+.

### 1. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then edit .env and paste your LLM_API_KEY (Gemini by default)
uvicorn app.main:app --reload --port 8000
```

The first time it starts you'll see logs like:

```
trading-agent: scheduler started
news_agent: inserted 746 articles
market_agent: inserted 11927 bars across 99 symbols
signal_agent: 84 candidates (top conf 0.80)
llm_agent: 10 suggestion(s) from gemini-2.5-flash
```

The market agent fetches all ~100 tickers sequentially on the first run — give it 2-3 minutes. Subsequent runs are quick (upserts).

The API is at `http://localhost:8000/api/health`, with auto-generated docs at `http://localhost:8000/docs`.

If you don't set `LLM_API_KEY`, the app still works — it'll skip the LLM step and save the top rule-based candidates so you can at least see something.

### 2. Frontend

In a separate terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The Vite dev server proxies `/api/*` to the backend, so it Just Works.

### 3. Pushing a manual refresh

There's a **Refresh now** button in the top-right of the UI — it triggers all three agents on demand. Same as hitting `POST /api/refresh`.

## Deploying it (so you can check from your phone)

The whole thing is small enough to run on the free tier of [Railway](https://railway.app), [Fly.io](https://fly.io), or [Render](https://render.com). The simplest path:

1. Build the frontend (`cd frontend && npm run build`) and serve the resulting `dist/` either from FastAPI directly (add a `StaticFiles` mount) or from a static host like Vercel.
2. Deploy the backend as a Python service, set the env vars from `.env.example`, and point the frontend at it.
3. SQLite lives on the container's disk — fine for single-user, but make sure your host gives you a persistent volume if you don't want to lose data on redeploys.

## A note on what this is and isn't

It's a thinking tool. It surfaces ideas that pass two filters — "the chart looks like X" and "the news supports X" — and writes them down for you. It doesn't place orders. It doesn't know your risk appetite. It doesn't replace doing your own homework.

The rule engine is intentionally simple (RSI/MACD/MAs are decades-old textbook stuff) and the LLM is just there to be the news-aware sanity check. If you find yourself trusting it blindly, that's a bug — make the rationale field force you to read the *why* before acting.
