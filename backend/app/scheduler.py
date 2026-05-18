from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from .agents.live_quotes_agent import run_live_quotes_agent
from .agents.llm_agent import run_llm_agent
from .agents.market_agent import run_market_agent
from .agents.news_agent import run_news_agent
from .config import settings

log = logging.getLogger(__name__)


def _safe(fn):
    def wrapper():
        try:
            fn()
        except Exception:
            log.exception("scheduled job %s failed", fn.__name__)
    wrapper.__name__ = fn.__name__
    return wrapper


def build_scheduler() -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone="Asia/Kolkata")
    sched.add_job(_safe(run_news_agent), "interval", minutes=settings.news_interval_min, id="news", next_run_time=None)
    sched.add_job(_safe(run_market_agent), "interval", minutes=settings.market_interval_min, id="market", next_run_time=None)
    sched.add_job(_safe(run_llm_agent), "interval", minutes=settings.signal_interval_min, id="signals", next_run_time=None)
    sched.add_job(_safe(run_live_quotes_agent), "interval", minutes=settings.live_quotes_interval_min, id="live_quotes", next_run_time=None)
    return sched
