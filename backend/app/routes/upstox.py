"""Upstox-facing routes: OAuth handshake, status, and a subscribable .ics
calendar feed that fires a daily reminder to refresh the token.

The .ics endpoint is intentionally *not* gated by the app auth dependency
(see main.py mounting) so that calendar apps which can't carry session
cookies can still subscribe — anyone hitting it just gets a static event
template; the embedded login URL still requires Upstox login to do anything.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse

from ..config import settings
from ..upstox.auth import build_login_url, exchange_code, is_configured, token_status

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/upstox/login")
def upstox_login(request: Request):
    if not is_configured():
        raise HTTPException(503, "upstox integration not configured (set UPSTOX_API_KEY/SECRET/REDIRECT_URI)")
    state = "trading-agent"  # we don't multiplex users, so a constant is fine
    request.session["upstox_oauth_state"] = state
    return RedirectResponse(build_login_url(state))


@router.get("/upstox/callback")
def upstox_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        raise HTTPException(400, f"upstox returned error: {error}")
    if not code:
        raise HTTPException(400, "missing ?code")
    expected = request.session.get("upstox_oauth_state")
    if expected and state and expected != state:
        raise HTTPException(400, "state mismatch (CSRF guard)")
    try:
        exchange_code(code)
    except Exception as e:
        log.exception("upstox: token exchange failed")
        raise HTTPException(502, f"token exchange failed: {e}")
    # Bounce back to the dashboard.
    return RedirectResponse("/")


@router.get("/upstox/status")
def upstox_status():
    return {
        "configured": is_configured(),
        "token": token_status(),
    }


@router.get("/upstox/refresh.ics", response_class=PlainTextResponse)
def upstox_refresh_ics(request: Request):
    """Subscribable iCalendar feed: one daily recurring event at the configured
    reminder time (default 08:00 IST) reminding you to click the login link.

    Subscribe once from your phone's calendar app (Google Calendar:
    Settings -> "Add by URL"). Your calendar will poll this URL periodically
    and pop a native notification each morning.
    """
    hhmm = settings.upstox_reminder_hhmm.zfill(4)
    hour, minute = int(hhmm[:2]), int(hhmm[2:])
    # Anchor the recurring series on a past Monday so all weekdays are covered.
    anchor = datetime(2026, 1, 5, hour, minute)  # Mon 2026-01-05
    dtstart = anchor.strftime("%Y%m%dT%H%M%S")
    dtend = (anchor + timedelta(minutes=15)).strftime("%Y%m%dT%H%M%S")
    dtstamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    base = str(request.base_url).rstrip("/")
    login_url = f"{base}/upstox/login"
    description = (
        f"Tap to refresh your Upstox live-feed token: {login_url}\\n\\n"
        f"Upstox access tokens expire at 03:30 IST each morning; this nudge "
        f"keeps the trading-agent dashboard's live ticker working through the day."
    )

    ics = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//trading-agent//upstox-refresh//EN\r\n"
        "CALSCALE:GREGORIAN\r\n"
        "METHOD:PUBLISH\r\n"
        "X-WR-CALNAME:Trading Agent — Upstox Refresh\r\n"
        "X-WR-TIMEZONE:Asia/Kolkata\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:upstox-refresh@trading-agent\r\n"
        f"DTSTAMP:{dtstamp}\r\n"
        f"DTSTART;TZID=Asia/Kolkata:{dtstart}\r\n"
        f"DTEND;TZID=Asia/Kolkata:{dtend}\r\n"
        "RRULE:FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR\r\n"
        "SUMMARY:Refresh Upstox token (trading-agent)\r\n"
        f"DESCRIPTION:{description}\r\n"
        f"URL:{login_url}\r\n"
        "BEGIN:VALARM\r\n"
        "ACTION:DISPLAY\r\n"
        "DESCRIPTION:Refresh Upstox token\r\n"
        "TRIGGER:-PT0M\r\n"
        "END:VALARM\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    return PlainTextResponse(ics, media_type="text/calendar; charset=utf-8")
