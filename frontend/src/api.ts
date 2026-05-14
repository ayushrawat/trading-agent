export interface Trade {
  id: number;
  created_at: string;
  symbol: string;
  direction: "LONG" | "SHORT";
  entry: number | null;
  stop: number | null;
  target: number | null;
  confidence: number | null;
  timeframe: string | null;
  rationale: string;
  signals: string[];
  news_refs: number[];
}

export interface NewsItem {
  id: number;
  source: string;
  title: string;
  url: string;
  published_at: string;
}

const BASE = "";

export async function fetchTrades(): Promise<Trade[]> {
  const r = await fetch(`${BASE}/api/trades`);
  if (!r.ok) throw new Error(`trades ${r.status}`);
  return r.json();
}

export async function fetchNews(): Promise<NewsItem[]> {
  const r = await fetch(`${BASE}/api/news`);
  if (!r.ok) throw new Error(`news ${r.status}`);
  return r.json();
}

export async function refreshNow(): Promise<void> {
  const r = await fetch(`${BASE}/api/refresh`, { method: "POST" });
  if (!r.ok) throw new Error(`refresh ${r.status}`);
}
