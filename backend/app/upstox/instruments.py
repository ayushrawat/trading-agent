"""Map our short symbols ("RELIANCE", "TCS", ...) to Upstox `instrument_key`s.

Upstox publishes a daily-updated JSON.gz of all instruments per exchange.
We download NSE.json.gz on first use (and refresh once a day), build a
`trading_symbol -> instrument_key` map, and use that to subscribe to the
right tokens on the WS feed.

Indices live on a different shape ("NSE_INDEX|Nifty 50", "BSE_INDEX|SENSEX")
and are hardcoded — these don't churn.
"""

from __future__ import annotations

import gzip
import io
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from ..universe import NIFTY_100

log = logging.getLogger(__name__)

_NSE_FEED = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
_CACHE_DIR = Path("/tmp")
_NSE_CACHE = _CACHE_DIR / "upstox_NSE.json.gz"
_MAX_CACHE_AGE = timedelta(hours=20)

# Indices use a different instrument-key shape and rarely change.
INDEX_KEYS: dict[str, str] = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "SENSEX": "BSE_INDEX|SENSEX",
}


def _cache_is_fresh() -> bool:
    if not _NSE_CACHE.is_file():
        return False
    age = datetime.utcnow() - datetime.utcfromtimestamp(_NSE_CACHE.stat().st_mtime)
    return age < _MAX_CACHE_AGE


def _download() -> None:
    log.info("upstox.instruments: downloading NSE instrument list")
    r = httpx.get(_NSE_FEED, timeout=30.0, follow_redirects=True)
    r.raise_for_status()
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _NSE_CACHE.write_bytes(r.content)


def _load_raw() -> list[dict]:
    if not _cache_is_fresh():
        try:
            _download()
        except Exception:
            log.exception("upstox.instruments: download failed; using stale cache if any")
            if not _NSE_CACHE.is_file():
                return []
    with gzip.open(_NSE_CACHE, "rb") as fh:
        return json.loads(fh.read().decode("utf-8"))


def build_symbol_map() -> dict[str, str]:
    """Return a dict mapping our short symbols (including indices) to Upstox
    instrument keys. Symbols we can't resolve are simply omitted; callers
    should log+skip them.
    """
    mapping: dict[str, str] = dict(INDEX_KEYS)
    wanted = {t for (t, _n, _yf) in NIFTY_100}

    try:
        rows = _load_raw()
    except Exception:
        log.exception("upstox.instruments: failed to load instrument file")
        return mapping

    # Upstox rows look roughly like:
    # { "instrument_key": "NSE_EQ|INE002A01018", "trading_symbol": "RELIANCE",
    #   "exchange": "NSE_EQ", "instrument_type": "EQ", "isin": "INE002A01018", ... }
    by_symbol: dict[str, str] = {}
    for row in rows:
        exch = row.get("exchange") or row.get("segment")
        if exch != "NSE_EQ":
            continue
        sym = row.get("trading_symbol") or row.get("tradingsymbol")
        key = row.get("instrument_key")
        if not sym or not key:
            continue
        by_symbol[sym] = key

    missing: list[str] = []
    for sym in wanted:
        if sym in by_symbol:
            mapping[sym] = by_symbol[sym]
        else:
            missing.append(sym)
    if missing:
        log.warning("upstox.instruments: %d symbols not found in NSE feed: %s",
                    len(missing), ", ".join(sorted(missing)[:8]) + ("..." if len(missing) > 8 else ""))
    return mapping
