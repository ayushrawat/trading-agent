from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..db import SessionLocal
from ..models import MarketBar
from ..universe import NIFTY_100

router = APIRouter()


class Quote(BaseModel):
    symbol: str
    name: str
    last: float | None
    prev: float | None
    change: float | None
    change_pct: float | None


class QuotesOut(BaseModel):
    indices: list[Quote]
    stocks: list[Quote]


def _last_two_closes(db, symbol: str) -> tuple[float | None, float | None]:
    rows = (
        db.query(MarketBar.close)
        .filter(MarketBar.symbol == symbol)
        .order_by(MarketBar.ts.desc())
        .limit(2)
        .all()
    )
    if not rows:
        return None, None
    last = rows[0][0]
    prev = rows[1][0] if len(rows) > 1 else None
    return last, prev


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
    """Latest close + previous close for indices and the NIFTY 100 universe.

    Uses the last two daily bars in `market_bars`. During market hours the
    market_agent refreshes daily bars so `last` tracks the live-ish close.
    """
    indices: list[Quote] = []
    stocks: list[Quote] = []
    with SessionLocal() as db:
        for sym in ("SENSEX", "NIFTY"):
            last, prev = _last_two_closes(db, sym)
            indices.append(_quote(sym, "BSE Sensex" if sym == "SENSEX" else "Nifty 50", last, prev))
        for ticker, name, _yf in NIFTY_100:
            last, prev = _last_two_closes(db, ticker)
            stocks.append(_quote(ticker, name, last, prev))
    return QuotesOut(indices=indices, stocks=stocks)
