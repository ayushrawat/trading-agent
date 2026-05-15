from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, UniqueConstraint, Index

from .db import Base


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id = Column(Integer, primary_key=True)
    source = Column(String(64), nullable=False)
    title = Column(String(512), nullable=False)
    url = Column(String(1024), nullable=False)
    summary = Column(Text, default="")
    published_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    fetched_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("url", name="uq_news_url"),
        Index("ix_news_published", "published_at"),
    )


class MarketBar(Base):
    __tablename__ = "market_bars"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(32), nullable=False)
    ts = Column(DateTime, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)

    __table_args__ = (
        UniqueConstraint("symbol", "ts", name="uq_bar_symbol_ts"),
        Index("ix_bar_symbol_ts", "symbol", "ts"),
    )


class TradeSuggestion(Base):
    __tablename__ = "trade_suggestions"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    symbol = Column(String(32), nullable=False)
    direction = Column(String(8), nullable=False)  # LONG / SHORT
    entry = Column(Float)
    stop = Column(Float)
    target = Column(Float)
    confidence = Column(Float)  # 0..1
    timeframe = Column(String(32), default="intraday")
    rationale = Column(Text, default="")
    signals_json = Column(Text, default="")  # rule signals that fired
    news_refs_json = Column(Text, default="")  # article ids referenced
    # Historical hit rate of this rule combo in this direction on this stock.
    # Null when insufficient history (e.g. newly listed or too few past signals).
    hit_rate = Column(Float, nullable=True)
    hit_rate_sample = Column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_trade_created", "created_at"),
    )
