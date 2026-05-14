from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from ..agents.llm_agent import run_llm_agent
from ..agents.market_agent import run_market_agent
from ..agents.news_agent import run_news_agent
from ..db import SessionLocal
from ..models import TradeSuggestion

router = APIRouter()


class TradeOut(BaseModel):
    id: int
    created_at: datetime
    symbol: str
    direction: str
    entry: float | None
    stop: float | None
    target: float | None
    confidence: float | None
    timeframe: str | None
    rationale: str
    signals: list[str]
    news_refs: list[int]


@router.get("/trades", response_model=list[TradeOut])
def list_trades(hours: int = 24, limit: int = 50):
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    with SessionLocal() as db:
        rows = (
            db.query(TradeSuggestion)
            .filter(TradeSuggestion.created_at >= cutoff)
            .order_by(TradeSuggestion.created_at.desc())
            .limit(limit)
            .all()
        )
    return [
        TradeOut(
            id=r.id,
            created_at=r.created_at,
            symbol=r.symbol,
            direction=r.direction,
            entry=r.entry,
            stop=r.stop,
            target=r.target,
            confidence=r.confidence,
            timeframe=r.timeframe,
            rationale=r.rationale or "",
            signals=json.loads(r.signals_json or "[]"),
            news_refs=json.loads(r.news_refs_json or "[]"),
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
