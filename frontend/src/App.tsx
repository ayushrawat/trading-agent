import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchMe,
  fetchNews,
  fetchQuotes,
  fetchTrades,
  LiveStatus,
  logout,
  Me,
  NewsItem,
  Quote,
  Quotes,
  refreshNow,
  Trade,
} from "./api";

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString();
}

function TradeCard({ trade, news }: { trade: Trade; news: NewsItem[] }) {
  const isLong = trade.direction === "LONG";
  const refs = trade.news_refs
    .map((id) => news.find((n) => n.id === id))
    .filter((n): n is NewsItem => !!n);

  return (
    <article className={`card ${isLong ? "long" : "short"}`}>
      <header>
        <div className="symbol-block">
          <div className="symbol">{trade.symbol}</div>
          {trade.name && trade.name !== trade.symbol && (
            <div className="name">{trade.name}</div>
          )}
        </div>
        <div className={`tag ${isLong ? "tag-long" : "tag-short"}`}>{trade.direction}</div>
        <div className="conf" title="confidence">
          {trade.confidence != null ? `${Math.round(trade.confidence * 100)}%` : "—"}
        </div>
      </header>
      <div className="levels">
        <div><span>Entry</span><b>{trade.entry ?? "—"}</b></div>
        <div><span>Stop</span><b>{trade.stop ?? "—"}</b></div>
        <div><span>Target</span><b>{trade.target ?? "—"}</b></div>
        <div title="Past-year hit rate of this rule combo on this stock">
          <span>Hit rate</span>
          <b>
            {trade.hit_rate != null
              ? `${Math.round(trade.hit_rate * 100)}%`
              : "—"}
          </b>
          {trade.hit_rate_sample != null && trade.hit_rate_sample > 0 && (
            <em>n={trade.hit_rate_sample}</em>
          )}
        </div>
      </div>
      <p className="rationale">{trade.rationale}</p>
      {trade.signals.length > 0 && (
        <ul className="signals">
          {trade.signals.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ul>
      )}
      {refs.length > 0 && (
        <div className="news-refs">
          <span>Driven by:</span>
          <ul>
            {refs.map((n) => (
              <li key={n.id}>
                <a href={n.url} target="_blank" rel="noreferrer">{n.title}</a>
                <em> — {n.source}</em>
              </li>
            ))}
          </ul>
        </div>
      )}
      <footer>{fmtTime(trade.created_at)} • {trade.timeframe}</footer>
    </article>
  );
}

function fmtNum(n: number | null, digits = 2): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function ChangeBlock({ change, pct }: { change: number | null; pct: number | null }) {
  if (change == null || pct == null) {
    return <span className="chg chg-flat">—</span>;
  }
  const up = change >= 0;
  const sign = up ? "+" : "";
  return (
    <span className={`chg ${up ? "chg-up" : "chg-down"}`}>
      {sign}
      {fmtNum(change)} ({sign}
      {fmtNum(pct)}%)
    </span>
  );
}

function LiveStatusBanner({ live }: { live: LiveStatus }) {
  // Only nag if Upstox is set up AND we're falling back. If Upstox isn't
  // configured at all, the yfinance-delayed feed is by design.
  if (!live.upstox_configured) return null;
  if (live.source === "upstox") return null;

  const tokenIssue = !live.upstox_token_valid;
  const msg = tokenIssue
    ? "Upstox token expired — live feed is ~15 min delayed (yfinance fallback)."
    : "Connecting to Upstox… live feed is ~15 min delayed (yfinance fallback).";
  const cta = tokenIssue ? "Refresh token" : "Reconnect";

  return (
    <div className="live-banner">
      <span className="live-dot" aria-hidden="true" />
      <span className="live-msg">{msg}</span>
      {live.login_url && (
        <a className="live-cta" href={live.login_url}>{cta} →</a>
      )}
    </div>
  );
}

function IndicesPanel({ indices }: { indices: Quote[] }) {
  if (indices.length === 0) return null;
  return (
    <div className="indices">
      {indices.map((q) => (
        <div key={q.symbol} className="index-card">
          <div className="index-name">{q.name}</div>
          <div className="index-last">{fmtNum(q.last)}</div>
          <ChangeBlock change={q.change} pct={q.change_pct} />
        </div>
      ))}
    </div>
  );
}

function TickerBar({ stocks }: { stocks: Quote[] }) {
  // Only show stocks we actually have a quote for. Duplicate the list so the
  // marquee loops seamlessly when translated -50%.
  const shown = useMemo(
    () => stocks.filter((s) => s.change_pct != null),
    [stocks],
  );
  if (shown.length === 0) return null;

  const renderItem = (q: Quote, i: number) => {
    const pct = q.change_pct!;
    const up = pct >= 0;
    return (
      <span key={`${q.symbol}-${i}`} className="tk-item">
        <span className="tk-sym">{q.symbol}</span>
        <span className="tk-last">{fmtNum(q.last)}</span>
        <span className={`tk-pct ${up ? "chg-up" : "chg-down"}`}>
          {up ? "+" : ""}
          {fmtNum(pct)}%
        </span>
      </span>
    );
  };

  return (
    <div className="ticker">
      <div className="ticker-track">
        <div className="ticker-row">{shown.map(renderItem)}</div>
        <div className="ticker-row" aria-hidden="true">
          {shown.map((q, i) => renderItem(q, i + shown.length))}
        </div>
      </div>
    </div>
  );
}

function LoginScreen() {
  return (
    <div className="login">
      <div className="login-card">
        <h1>Trading Agent</h1>
        <p>Sign in with the Google account that's been added to the allowlist.</p>
        <a className="google-btn" href="/auth/login">
          Sign in with Google
        </a>
      </div>
    </div>
  );
}

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [meLoading, setMeLoading] = useState(true);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [news, setNews] = useState<NewsItem[]>([]);
  const [quotes, setQuotes] = useState<Quotes>({
    indices: [],
    stocks: [],
    live: {
      source: "stale",
      upstox_configured: false,
      upstox_connected: false,
      upstox_token_valid: false,
      market_open: false,
      login_url: null,
    },
  });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMe()
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setMeLoading(false));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [t, n, q] = await Promise.all([fetchTrades(), fetchNews(), fetchQuotes()]);
      setTrades(t);
      setNews(n);
      setQuotes(q);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg === "unauthorized") {
        // session may have expired — re-check /me
        fetchMe().then(setMe).catch(() => setMe(null));
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const isAuthed = !me?.auth_required || me?.authenticated;

  useEffect(() => {
    if (!isAuthed) return;
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, [load, isAuthed]);

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await refreshNow();
      setTimeout(load, 4000);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRefreshing(false);
    }
  };

  const onLogout = async () => {
    await logout();
    setMe({ ...(me as Me), authenticated: false, email: null, name: null, picture: null });
  };

  if (meLoading) {
    return <div className="page"><div className="empty">Loading…</div></div>;
  }

  if (me?.auth_required && !me.authenticated) {
    return <LoginScreen />;
  }

  return (
    <>
      <TickerBar stocks={quotes.stocks} />
      <LiveStatusBanner live={quotes.live} />
      <div className="page">
        <header className="topbar">
          <h1>Trading Agent <span>· NIFTY 100 picks</span></h1>
          <div className="topbar-actions">
            {me?.authenticated && me.email && (
              <div className="user-chip">
                {me.picture && <img src={me.picture} alt="" />}
                <span>{me.email}</span>
                <button className="link-btn" onClick={onLogout}>Sign out</button>
              </div>
            )}
            <button onClick={onRefresh} disabled={refreshing}>
              {refreshing ? "Refreshing…" : "Refresh now"}
            </button>
          </div>
        </header>

        <IndicesPanel indices={quotes.indices} />

        {error && <div className="err">Error: {error}</div>}

        {loading && trades.length === 0 ? (
          <div className="empty">Loading suggestions…</div>
        ) : trades.length === 0 ? (
          <div className="empty">
            No suggestions yet. The agents may still be warming up — try refresh in a minute.
          </div>
        ) : (
          <div className="grid">
            {trades.map((t) => (
              <TradeCard key={t.id} trade={t} news={news} />
            ))}
          </div>
        )}

        <section className="news-section">
          <h2>Recent news</h2>
          {news.length === 0 ? (
            <div className="empty">No news fetched yet.</div>
          ) : (
            <ul className="news-list">
              {news.slice(0, 20).map((n) => (
                <li key={n.id}>
                  <a href={n.url} target="_blank" rel="noreferrer">{n.title}</a>
                  <span className="news-meta"> — {n.source} · {fmtTime(n.published_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}
