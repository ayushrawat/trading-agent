"""Google OAuth + email allowlist.

Enable by setting AUTH_ENABLED=true and providing GOOGLE_CLIENT_ID,
GOOGLE_CLIENT_SECRET, ALLOWED_EMAILS_RAW, SESSION_SECRET. When disabled,
require_user() is a no-op and the routes are open.
"""
from __future__ import annotations

import logging

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from .config import settings

log = logging.getLogger(__name__)

router = APIRouter()

oauth = OAuth()
if settings.auth_enabled and settings.google_client_id:
    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


def _callback_url(request: Request) -> str:
    if settings.oauth_redirect_uri:
        return settings.oauth_redirect_uri
    # str(request.url_for(...)) on FastAPI returns the absolute URL
    return str(request.url_for("auth_callback"))


@router.get("/auth/login")
async def login(request: Request):
    if not settings.auth_enabled:
        return RedirectResponse("/")
    return await oauth.google.authorize_redirect(request, _callback_url(request))


@router.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as e:
        log.warning("OAuth error: %s", e)
        raise HTTPException(status_code=401, detail="OAuth failed")
    user = token.get("userinfo") or {}
    email = (user.get("email") or "").lower()
    if not email:
        raise HTTPException(status_code=401, detail="No email returned by Google")
    if email not in settings.allowed_emails:
        log.warning("denied OAuth login for non-allowlisted email: %s", email)
        # render a tiny HTML page so the user understands what happened
        from fastapi.responses import HTMLResponse
        return HTMLResponse(
            f"<h1>Access denied</h1><p><code>{email}</code> is not on the allowlist.</p>"
            f"<p><a href='/auth/logout'>Try another account</a></p>",
            status_code=403,
        )
    request.session["user_email"] = email
    request.session["user_name"] = user.get("name", "")
    request.session["user_picture"] = user.get("picture", "")
    log.info("auth: login ok for %s", email)
    return RedirectResponse("/")


@router.post("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return {"status": "ok"}


@router.get("/auth/logout")
async def logout_get(request: Request):
    """Same as POST /auth/logout but reachable via a link."""
    request.session.clear()
    return RedirectResponse("/")


class MeOut(BaseModel):
    authenticated: bool
    email: str | None = None
    name: str | None = None
    picture: str | None = None
    auth_required: bool


@router.get("/api/me", response_model=MeOut)
async def me(request: Request):
    email = request.session.get("user_email")
    return MeOut(
        authenticated=bool(email),
        email=email,
        name=request.session.get("user_name") or None,
        picture=request.session.get("user_picture") or None,
        auth_required=settings.auth_enabled,
    )


def require_user(request: Request) -> str:
    """FastAPI dependency. Returns the user's email or 401s."""
    if not settings.auth_enabled:
        return "anonymous"
    email = request.session.get("user_email")
    if not email:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if email not in settings.allowed_emails:
        # Allowlist was edited after the user logged in.
        request.session.clear()
        raise HTTPException(status_code=403, detail="Not in allowlist")
    return email
