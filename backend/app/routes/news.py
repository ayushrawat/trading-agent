from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel

from ..db import SessionLocal
from ..models import NewsArticle

router = APIRouter()


class NewsOut(BaseModel):
    id: int
    source: str
    title: str
    url: str
    published_at: datetime


@router.get("/news", response_model=list[NewsOut])
def list_news(hours: int = 24, limit: int = 50):
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    with SessionLocal() as db:
        rows = (
            db.query(NewsArticle)
            .filter(NewsArticle.published_at >= cutoff)
            .order_by(NewsArticle.published_at.desc())
            .limit(limit)
            .all()
        )
    return [
        NewsOut(
            id=r.id,
            source=r.source,
            title=r.title,
            url=r.url,
            published_at=r.published_at,
        )
        for r in rows
    ]
