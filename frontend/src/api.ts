export interface Trade {
  id: number;
  created_at: string;
  symbol: string;
  name: string;
  direction: "LONG" | "SHORT";
  entry: number | null;
  stop: number | null;
  target: number | null;
  confidence: number | null;
  timeframe: string | null;
  rationale: string;
  signals: string[];
  news_refs: number[];
  hit_rate: number | null;
  hit_rate_sample: number | null;
}

export interface NewsItem {
  id: number;
  source: string;
  title: string;
  url: string;
  published_at: string;
}

const BASE = "";

export interface Me {
  authenticated: boolean;
  email: string | null;
  name: string | null;
  picture: string | null;
  auth_required: boolean;
}

export async function fetchMe(): Promise<Me> {
  const r = await fetch(`${BASE}/api/me`, { credentials: "include" });
  if (!r.ok) throw new Error(`me ${r.status}`);
  return r.json();
}

export async function logout(): Promise<void> {
  await fetch(`${BASE}/auth/logout`, { method: "POST", credentials: "include" });
}

export async function fetchTrades(): Promise<Trade[]> {
  const r = await fetch(`${BASE}/api/trades`, { credentials: "include" });
  if (r.status === 401) throw new Error("unauthorized");
  if (!r.ok) throw new Error(`trades ${r.status}`);
  return r.json();
}

export async function fetchNews(): Promise<NewsItem[]> {
  const r = await fetch(`${BASE}/api/news`, { credentials: "include" });
  if (!r.ok) throw new Error(`news ${r.status}`);
  return r.json();
}

export interface Quote {
  symbol: string;
  name: string;
  last: number | null;
  prev: number | null;
  change: number | null;
  change_pct: number | null;
}

export interface LiveStatus {
  source: "upstox" | "yfinance" | "stale";
  upstox_configured: boolean;
  upstox_connected: boolean;
  upstox_token_valid: boolean;
  market_open: boolean;
  login_url: string | null;
}

export interface Quotes {
  indices: Quote[];
  stocks: Quote[];
  live: LiveStatus;
}

export async function fetchQuotes(): Promise<Quotes> {
  const r = await fetch(`${BASE}/api/quotes`, { credentials: "include" });
  if (r.status === 401) throw new Error("unauthorized");
  if (!r.ok) throw new Error(`quotes ${r.status}`);
  return r.json();
}

export async function refreshNow(): Promise<void> {
  const r = await fetch(`${BASE}/api/refresh`, { method: "POST", credentials: "include" });
  if (!r.ok) throw new Error(`refresh ${r.status}`);
}
