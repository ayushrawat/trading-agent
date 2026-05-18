from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .agents.live_quotes_agent import run_live_quotes_agent
from .agents.llm_agent import run_llm_agent
from .agents.market_agent import run_market_agent
from .agents.news_agent import run_news_agent
from .auth import require_user, router as auth_router
from .config import settings
from .db import init_db
from .routes.news import router as news_router
from .routes.quotes import router as quotes_router
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
    import threading
    def _boot():
        try:
            run_news_agent()
            run_market_agent()
            run_live_quotes_agent()
            run_llm_agent()
        except Exception:
            log.exception("initial boot pass failed")
    threading.Thread(target=_boot, daemon=True).start()
    log.info("trading-agent: scheduler started (auth_enabled=%s)", settings.auth_enabled)
    try:
        yield
    finally:
        sched.shutdown(wait=False)


app = FastAPI(title="Trading Agent", lifespan=lifespan)

# Sessions back our OAuth flow + carry user email after login.
# In production (Fly) the platform terminates TLS so requests reach us as
# HTTP — Starlette sets Secure cookies based on the request scheme, so
# the cookies will still be marked Secure when the original request was HTTPS.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",
    https_only=False,  # Starlette respects X-Forwarded-Proto via the proxy header middleware
    max_age=60 * 60 * 24 * 14,  # 14 days
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth router (login/callback/logout/me) — never requires auth itself.
app.include_router(auth_router, tags=["auth"])

# Application routers — gated by require_user when auth is enabled.
_auth_deps = [Depends(require_user)] if settings.auth_enabled else []
app.include_router(trades_router, prefix="/api", tags=["trades"], dependencies=_auth_deps)
app.include_router(news_router, prefix="/api", tags=["news"], dependencies=_auth_deps)
app.include_router(quotes_router, prefix="/api", tags=["quotes"], dependencies=_auth_deps)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve the built React SPA. The Dockerfile copies frontend/dist into
# backend/static/. When running locally without a build, the directory may
# not exist — in that case we skip mounting and you use `npm run dev`.
_STATIC_DIR = Path(__file__).parent.parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=_STATIC_DIR / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(_STATIC_DIR / "index.html")

    @app.get("/{path:path}")
    def spa_fallback(path: str):
        # Any non-API path falls back to index.html (for client-side routing).
        candidate = _STATIC_DIR / path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_STATIC_DIR / "index.html")
