import { useCallback, useEffect, useState } from "react";
import { fetchNews, fetchTrades, NewsItem, refreshNow, Trade } from "./api";

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
        <div className="symbol">{trade.symbol}</div>
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

export default function App() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [news, setNews] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [t, n] = await Promise.all([fetchTrades(), fetchNews()]);
      setTrades(t);
      setNews(n);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, [load]);

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await refreshNow();
      // give the background tasks a few seconds, then reload
      setTimeout(load, 4000);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div className="page">
      <header className="topbar">
        <h1>Trading Agent <span>· NIFTY / SENSEX</span></h1>
        <button onClick={onRefresh} disabled={refreshing}>
          {refreshing ? "Refreshing…" : "Refresh now"}
        </button>
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
