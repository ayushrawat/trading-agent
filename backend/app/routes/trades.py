from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import func

from ..agents.llm_agent import run_llm_agent
from ..agents.market_agent import run_market_agent
from ..agents.news_agent import run_news_agent
from ..db import SessionLocal
from ..models import TradeSuggestion
from ..universe import NIFTY_100

router = APIRouter()

# ticker -> human-readable name
_NAME_BY_TICKER: dict[str, str] = {t: n for (t, n, _yf) in NIFTY_100}


class TradeOut(BaseModel):
    id: int
    created_at: datetime
    symbol: str
    name: str
    direction: str
    entry: float | None
    stop: float | None
    target: float | None
    confidence: float | None
    timeframe: str | None
    rationale: str
    signals: list[str]
    news_refs: list[int]
    hit_rate: float | None
    hit_rate_sample: int | None


@router.get("/trades", response_model=list[TradeOut])
def list_trades(limit: int = 20):
    """Return the most recent batch of suggestions (the cluster of rows whose
    created_at is within ~2 minutes of the latest), ordered by confidence DESC.
    """
    with SessionLocal() as db:
        latest = db.query(func.max(TradeSuggestion.created_at)).scalar()
        if latest is None:
            return []
        cutoff = latest - timedelta(minutes=2)
        rows = (
            db.query(TradeSuggestion)
            .filter(TradeSuggestion.created_at >= cutoff)
            .order_by(TradeSuggestion.confidence.desc().nulls_last(), TradeSuggestion.created_at.desc())
            .limit(limit)
            .all()
        )
    return [
        TradeOut(
            id=r.id,
            created_at=r.created_at,
            symbol=r.symbol,
            name=_NAME_BY_TICKER.get(r.symbol, r.symbol),
            direction=r.direction,
            entry=r.entry,
            stop=r.stop,
            target=r.target,
            confidence=r.confidence,
            timeframe=r.timeframe,
            rationale=r.rationale or "",
            signals=json.loads(r.signals_json or "[]"),
            news_refs=json.loads(r.news_refs_json or "[]"),
            hit_rate=r.hit_rate,
            hit_rate_sample=r.hit_rate_sample,
        )
        for r in rows
    ]


class RefreshOut(BaseModel):
    status: str


@router.post("/refresh", response_model=RefreshOut)
def refresh_now(background: BackgroundTasks):
    background.add_task(run_news_agent)
    background.add_task(run_market_agent)
    background.add_task(run_llm_agent)
    return RefreshOut(status="scheduled")
