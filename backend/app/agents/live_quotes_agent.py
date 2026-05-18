"""Live (~15-min delayed by yfinance) intraday quote refresher.

During NSE/BSE market hours we batch-fetch 1-minute bars for the entire
universe in a single yf.download call and stash the latest close per symbol
in a process-wide cache. The /api/quotes endpoint reads from this cache so
the ticker + index cards feel live instead of stuck on yesterday's close.

Outside market hours the function is a no-op; the endpoint silently falls
back to the most recent daily bar.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from ..config import settings
from ..universe import NIFTY_100

log = logging.getLogger(__name__)

_IST = ZoneInfo("Asia/Kolkata")

# Indices fetched alongside stocks; same (display_symbol, yf_ticker) shape used elsewhere.
_INDICES: list[tuple[str, str]] = [
    ("NIFTY", "^NSEI"),
    ("SENSEX", "^BSESN"),
]

# (display_symbol, yf_ticker) for every symbol we want a live quote for.
_ALL: list[tuple[str, str]] = _INDICES + [(t, yf_t) for (t, _n, yf_t) in NIFTY_100]

# Process-wide cache: symbol -> (last_price, fetched_at_utc).
_cache: dict[str, tuple[float, datetime]] = {}
_cache_lock = threading.Lock()


def _parse_hhmm(s: str) -> time:
    s = s.zfill(4)
    return time(hour=int(s[:2]), minute=int(s[2:]))


def _is_market_open(now_ist: datetime | None = None) -> bool:
    now = now_ist or datetime.now(_IST)
    if now.weekday() >= 5:  # 5=Sat, 6=Sun
        return False
    open_t = _parse_hhmm(settings.market_open_hhmm)
    close_t = _parse_hhmm(settings.market_close_hhmm)
    return open_t <= now.time() <= close_t


def get_cached_quote(symbol: str, max_age_min: int = 15) -> float | None:
    """Return the cached last price for `symbol` if it's recent enough, else None."""
    with _cache_lock:
        hit = _cache.get(symbol)
    if hit is None:
        return None
    price, fetched_at = hit
    age = (datetime.utcnow() - fetched_at).total_seconds() / 60.0
    if age > max_age_min:
        return None
    return price


def run_live_quotes_agent() -> int:
    """Refresh the in-process live-quote cache for indices + NIFTY 100.

    Returns the number of symbols updated. No-op outside market hours.
    """
    if not _is_market_open():
        log.debug("live_quotes: market closed, skipping refresh")
        return 0

    yf_tickers = [yf_t for (_s, yf_t) in _ALL]
    by_yf_ticker = {yf_t: sym for (sym, yf_t) in _ALL}

    try:
        df = yf.download(
            tickers=" ".join(yf_tickers),
            period="1d",
            interval="1m",
            group_by="ticker",
            auto_adjust=False,
            threads=True,
            progress=False,
        )
    except Exception:
        log.exception("live_quotes: batch yf.download failed")
        return 0

    if df is None or df.empty:
        log.warning("live_quotes: yf.download returned empty frame")
        return 0

    now_utc = datetime.utcnow()
    updated = 0
    # yf.download with group_by="ticker" yields a column MultiIndex of (yf_ticker, ohlcv_field).
    # Single-ticker frames come back flat, but we always pass >=2 here.
    for yf_t, sym in by_yf_ticker.items():
        try:
            sub = df[yf_t]
        except KeyError:
            continue
        closes = sub["Close"].dropna() if "Close" in sub else pd.Series(dtype=float)
        if closes.empty:
            continue
        last_price = float(closes.iloc[-1])
        if last_price != last_price:  # NaN guard
            continue
        with _cache_lock:
            _cache[sym] = (last_price, now_utc)
        updated += 1

    log.info("live_quotes: refreshed %d/%d symbols", updated, len(_ALL))
    return updated
