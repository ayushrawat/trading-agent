import { useCallback, useEffect, useState } from "react";
import { fetchMe, fetchNews, fetchTrades, logout, Me, NewsItem, refreshNow, Trade } from "./api";

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
      const [t, n] = await Promise.all([fetchTrades(), fetchNews()]);
      setTrades(t);
      setNews(n);
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
  );
}
