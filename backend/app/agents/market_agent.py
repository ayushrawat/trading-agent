from __future__ import annotations

import logging

import yfinance as yf
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..db import SessionLocal
from ..models import MarketBar
from ..universe import NIFTY_100

log = logging.getLogger(__name__)

# Build the full fetch list: indices first (kept for macro context but not
# surfaced as trades anymore), then NIFTY 100 stocks.
INDICES: list[tuple[str, str]] = [
    ("NIFTY", "^NSEI"),
    ("SENSEX", "^BSESN"),
]

SYMBOLS: list[tuple[str, str]] = INDICES + [(t, yf) for (t, _name, yf) in NIFTY_100]


def _fetch_one(yf_ticker: str, period: str, interval: str):
    try:
        df = yf.Ticker(yf_ticker).history(
            period=period,
            interval=interval,
            auto_adjust=False,
        )
        return df
    except Exception as e:
        log.warning("yfinance fetch failed %s: %s", yf_ticker, e)
        return None


def run_market_agent(period: str = "1y", interval: str = "1d") -> int:
    """Fetch OHLCV for indices + the full NIFTY 100 universe."""
    inserted = 0
    empty: list[str] = []
    with SessionLocal() as db:
        for symbol, yf_ticker in SYMBOLS:
            df = _fetch_one(yf_ticker, period, interval)
            if df is None or df.empty:
                empty.append(yf_ticker)
                continue

            rows = []
            for ts, row in df.iterrows():
                py_ts = ts.to_pydatetime()
                if py_ts.tzinfo is not None:
                    py_ts = py_ts.replace(tzinfo=None)
                rows.append({
                    "symbol": symbol,
                    "ts": py_ts,
                    "open": float(row["Open"]) if row["Open"] == row["Open"] else None,
                    "high": float(row["High"]) if row["High"] == row["High"] else None,
                    "low": float(row["Low"]) if row["Low"] == row["Low"] else None,
                    "close": float(row["Close"]) if row["Close"] == row["Close"] else None,
                    "volume": float(row["Volume"]) if row["Volume"] == row["Volume"] else None,
                })
            if not rows:
                continue
            stmt = sqlite_insert(MarketBar).values(rows)
            stmt = stmt.on_conflict_do_nothing(index_elements=["symbol", "ts"])
            result = db.execute(stmt)
            inserted += result.rowcount or 0
        db.commit()
    if empty:
        log.info("market_agent: %d tickers returned empty (likely delisted/renamed): %s",
                 len(empty), ", ".join(empty[:8]) + ("..." if len(empty) > 8 else ""))
    log.info("market_agent: inserted %d bars across %d symbols", inserted, len(SYMBOLS) - len(empty))
    return inserted
