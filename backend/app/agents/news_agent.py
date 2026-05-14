from __future__ import annotations

import logging
from datetime import datetime
from time import mktime

import feedparser

from ..db import SessionLocal
from ..models import NewsArticle

log = logging.getLogger(__name__)

# Verified working & fresh as of 2026-05-14. Moneycontrol/BS/NDTV-Profit/FE
# were dropped (stale, 403, or empty). See news source validation notes.
FEEDS: list[tuple[str, str]] = [
    ("ET Top Stories", "https://economictimes.indiatimes.com/rssfeedstopstories.cms"),
    ("ET Markets Stocks", "https://economictimes.indiatimes.com/markets/stocks/news/rssfeeds/2146843.cms"),
    ("ET Markets IPO", "https://economictimes.indiatimes.com/markets/ipo/rssfeeds/2146846.cms"),
    ("LiveMint News", "https://www.livemint.com/rss/news"),
    ("LiveMint Companies", "https://www.livemint.com/rss/companies"),
    ("LiveMint Money", "https://www.livemint.com/rss/money"),
    ("CNBC TV18 Market", "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml"),
    ("CNBC TV18 Economy", "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/economy.xml"),
    ("BusinessLine Markets", "https://www.thehindubusinessline.com/markets/feeder/default.rss"),
    ("BusinessLine Economy", "https://www.thehindubusinessline.com/economy/feeder/default.rss"),
    ("Investing.com India", "https://in.investing.com/rss/news.rss"),
    ("Investing.com Indicators", "https://in.investing.com/rss/news_25.rss"),
]

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


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
                feed = feedparser.parse(url, request_headers={"User-Agent": _UA})
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
