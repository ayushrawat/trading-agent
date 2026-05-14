from __future__ import annotations

import logging

import yfinance as yf
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..db import SessionLocal
from ..models import MarketBar

log = logging.getLogger(__name__)

SYMBOLS: dict[str, str] = {
    "NIFTY": "^NSEI",
    "SENSEX": "^BSESN",
}


def run_market_agent(period: str = "6mo", interval: str = "1d") -> int:
    """Fetch OHLCV for tracked indices; upsert into market_bars."""
    inserted = 0
    with SessionLocal() as db:
        for symbol, yf_ticker in SYMBOLS.items():
            try:
                df = yf.Ticker(yf_ticker).history(
                    period=period,
                    interval=interval,
                    auto_adjust=False,
                )
            except Exception as e:
                log.warning("yfinance fetch failed %s: %s", yf_ticker, e)
                continue
            if df is None or df.empty:
                log.warning("yfinance empty for %s", yf_ticker)
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
    log.info("market_agent: inserted %d bars", inserted)
    return inserted
