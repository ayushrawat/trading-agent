"""Upstox OAuth helpers + token store.

Upstox V2 OAuth flow:
  1. Redirect user to:
     https://api.upstox.com/v2/login/authorization/dialog
       ?client_id=<api_key>&redirect_uri=<...>&response_type=code&state=<csrf>
  2. User logs in. Upstox redirects back to <redirect_uri>?code=<...>&state=<...>
  3. POST https://api.upstox.com/v2/login/authorization/token
       form: code, client_id, client_secret, redirect_uri, grant_type=authorization_code
     Response: { access_token, expires_in, user_name, email, ... }

Access tokens expire at 3:30 AM IST (next-day expiry regardless of issue time),
so we recompute expires_at from the next 3:30 AM IST boundary rather than
trusting the seconds-based `expires_in` field, which has been inconsistent.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, time, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx

from ..config import settings
from ..db import SessionLocal
from ..models import UpstoxToken

log = logging.getLogger(__name__)

_IST = ZoneInfo("Asia/Kolkata")

AUTHORIZE_URL = "https://api.upstox.com/v2/login/authorization/dialog"
TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"


def is_configured() -> bool:
    return bool(settings.upstox_api_key and settings.upstox_api_secret and settings.upstox_redirect_uri)


def build_login_url(state: str | None = None) -> str:
    state = state or secrets.token_urlsafe(16)
    params = {
        "client_id": settings.upstox_api_key,
        "redirect_uri": settings.upstox_redirect_uri,
        "response_type": "code",
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _next_330am_ist(now_ist: datetime | None = None) -> datetime:
    now = now_ist or datetime.now(_IST)
    cutoff_today = datetime.combine(now.date(), time(3, 30), tzinfo=_IST)
    if now < cutoff_today:
        return cutoff_today
    return cutoff_today + timedelta(days=1)


def exchange_code(code: str) -> UpstoxToken:
    """Trade an auth code for an access token. Persists the result and returns
    the stored row.
    """
    resp = httpx.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.upstox_api_key,
            "client_secret": settings.upstox_api_secret,
            "redirect_uri": settings.upstox_redirect_uri,
            "grant_type": "authorization_code",
        },
        headers={"Accept": "application/json"},
        timeout=15.0,
    )
    resp.raise_for_status()
    body = resp.json()
    access_token = body.get("access_token")
    if not access_token:
        raise RuntimeError(f"upstox token response missing access_token: {body}")

    obtained_at = datetime.utcnow()
    expires_at_ist = _next_330am_ist()
    expires_at = expires_at_ist.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

    with SessionLocal() as db:
        row = db.get(UpstoxToken, 1)
        if row is None:
            row = UpstoxToken(id=1, access_token=access_token, obtained_at=obtained_at, expires_at=expires_at)
            db.add(row)
        else:
            row.access_token = access_token
            row.obtained_at = obtained_at
            row.expires_at = expires_at
        db.commit()
        db.refresh(row)
        log.info("upstox: stored fresh token, expires_at=%s UTC", expires_at.isoformat())
        return row


def get_active_token() -> str | None:
    """Return the current access token string if it's still valid, else None."""
    with SessionLocal() as db:
        row = db.get(UpstoxToken, 1)
    if row is None:
        return None
    if row.expires_at <= datetime.utcnow():
        return None
    return row.access_token


def token_status() -> dict:
    """Diagnostic blob for the dashboard banner."""
    with SessionLocal() as db:
        row = db.get(UpstoxToken, 1)
    if row is None:
        return {"present": False, "expired": True, "expires_at": None}
    return {
        "present": True,
        "expired": row.expires_at <= datetime.utcnow(),
        "expires_at": row.expires_at.replace(tzinfo=ZoneInfo("UTC")).isoformat(),
    }
