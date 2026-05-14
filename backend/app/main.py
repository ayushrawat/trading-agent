from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agents.llm_agent import run_llm_agent
from .agents.market_agent import run_market_agent
from .agents.news_agent import run_news_agent
from .db import init_db
from .routes.news import router as news_router
from .routes.trades import router as trades_router
from .scheduler import build_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    sched = build_scheduler()
    sched.start()
    # kick off an initial pass in the background so the UI is non-empty fast
    import threading
    def _boot():
        try:
            run_news_agent()
            run_market_agent()
            run_llm_agent()
        except Exception:
            log.exception("initial boot pass failed")
    threading.Thread(target=_boot, daemon=True).start()
    log.info("trading-agent: scheduler started")
    try:
        yield
    finally:
        sched.shutdown(wait=False)


app = FastAPI(title="Trading Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(trades_router, prefix="/api", tags=["trades"])
app.include_router(news_router, prefix="/api", tags=["news"])


@app.get("/api/health")
def health():
    return {"status": "ok"}
