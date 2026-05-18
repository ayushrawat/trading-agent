from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from pydantic import BaseModel

from ..agents.live_quotes_agent import _is_market_open, get_cached_quote
from ..db import SessionLocal
from ..models import MarketBar
from ..universe import NIFTY_100
from ..upstox import auth as upstox_auth
from ..upstox import ws_agent as upstox_ws

router = APIRouter()

_IST = ZoneInfo("Asia/Kolkata")


class Quote(BaseModel):
    symbol: str
    name: str
    last: float | None
    prev: float | None
    change: float | None
    change_pct: float | None


class LiveStatus(BaseModel):
    # 'upstox' = real-time WS feed live; 'yfinance' = ~15 min delayed fallback;
    # 'stale' = no fresh data from any source (market closed or fetch failures).
    source: str
    upstox_configured: bool
    upstox_connected: bool
    upstox_token_valid: bool
    market_open: bool
    login_url: str | None


class QuotesOut(BaseModel):
    indices: list[Quote]
    stocks: list[Quote]
    live: LiveStatus


def _live_status() -> LiveStatus:
    configured = upstox_auth.is_configured()
    token = upstox_auth.token_status()
    ws = upstox_ws.status()
    token_valid = bool(token.get("present") and not token.get("expired"))
    connected = bool(ws.get("connected"))
    market_open = _is_market_open()

    if connected and token_valid:
        source = "upstox"
    elif market_open:
        source = "yfinance"
    else:
        source = "stale"

    login_url = "/upstox/login" if configured and not connected else None
    return LiveStatus(
        source=source,
        upstox_configured=configured,
        upstox_connected=connected,
        upstox_token_valid=token_valid,
        market_open=market_open,
        login_url=login_url,
    )


def _daily_anchor(db, symbol: str) -> tuple[float | None, float | None]:
    """Return (latest_close, prev_close) from market_bars.

    `prev_close` is the last bar dated strictly before *today (IST)* so the
    day-over-day change keeps a stable baseline even when an intraday bar for
    today already exists in the table. `latest_close` is the most recent bar
    (used as a fallback when the live cache is empty).
    """
    rows = (
        db.query(MarketBar.ts, MarketBar.close)
        .filter(MarketBar.symbol == symbol)
        .order_by(MarketBar.ts.desc())
        .limit(5)
        .all()
    )
    if not rows:
        return None, None

    today_ist = datetime.now(_IST).date()
    latest_close = rows[0][1]
    prev_close = None
    for ts, close in rows:
        # market_bars timestamps are naive UTC-ish from yfinance; compare on date.
        if ts.date() < today_ist:
            prev_close = close
            break
    if prev_close is None and len(rows) > 1:
        prev_close = rows[1][1]
    return latest_close, prev_close


def _quote(symbol: str, display_name: str, last: float | None, prev: float | None) -> Quote:
    change = change_pct = None
    if last is not None and prev is not None and prev != 0:
        change = last - prev
        change_pct = (change / prev) * 100.0
    return Quote(
        symbol=symbol,
        name=display_name,
        last=last,
        prev=prev,
        change=change,
        change_pct=change_pct,
    )


@router.get("/quotes", response_model=QuotesOut)
def list_quotes():
    """Latest price + day's previous close for indices and the NIFTY 100 universe.

    During market hours `last` is served from the in-process live-quote cache
    (refreshed every few minutes via the scheduler). Outside market hours, or
    when the cache is empty/stale, falls back to the most recent daily bar.
    """
    indices: list[Quote] = []
    stocks: list[Quote] = []
    with SessionLocal() as db:
        for sym in ("SENSEX", "NIFTY"):
            daily_last, prev = _daily_anchor(db, sym)
            live = get_cached_quote(sym)
            last = live if live is not None else daily_last
            indices.append(_quote(sym, "BSE Sensex" if sym == "SENSEX" else "Nifty 50", last, prev))
        for ticker, name, _yf in NIFTY_100:
            daily_last, prev = _daily_anchor(db, ticker)
            live = get_cached_quote(ticker)
            last = live if live is not None else daily_last
            stocks.append(_quote(ticker, name, last, prev))
    return QuotesOut(indices=indices, stocks=stocks, live=_live_status())
