from __future__ import annotations

import logging
from datetime import datetime
from time import mktime

import feedparser

from ..db import SessionLocal
from ..models import NewsArticle

log = logging.getLogger(__name__)

FEEDS: list[tuple[str, str]] = [
    ("Moneycontrol Markets", "https://www.moneycontrol.com/rss/marketreports.xml"),
    ("Moneycontrol Business", "https://www.moneycontrol.com/rss/business.xml"),
    ("ET Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("ET Economy", "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms"),
    ("LiveMint Markets", "https://www.livemint.com/rss/markets"),
]


def _parse_published(entry) -> datetime:
    if getattr(entry, "published_parsed", None):
        return datetime.fromtimestamp(mktime(entry.published_parsed))
    if getattr(entry, "updated_parsed", None):
        return datetime.fromtimestamp(mktime(entry.updated_parsed))
    return datetime.utcnow()


def run_news_agent() -> int:
    """Fetch all feeds, insert new articles. Returns count inserted."""
    inserted = 0
    with SessionLocal() as db:
        existing = {url for (url,) in db.query(NewsArticle.url).all()}
        for source, url in FEEDS:
            try:
                feed = feedparser.parse(url)
            except Exception as e:
                log.warning("feed parse failed %s: %s", url, e)
                continue
            for entry in feed.entries:
                link = getattr(entry, "link", None)
                title = getattr(entry, "title", None)
                if not link or not title or link in existing:
                    continue
                article = NewsArticle(
                    source=source,
                    title=title[:512],
                    url=link[:1024],
                    summary=(getattr(entry, "summary", "") or "")[:4000],
                    published_at=_parse_published(entry),
                )
                db.add(article)
                existing.add(link)
                inserted += 1
        db.commit()
    log.info("news_agent: inserted %d articles", inserted)
    return inserted
