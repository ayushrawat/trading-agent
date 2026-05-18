"""Upstox V3 market-data WebSocket client.

Runs in a background daemon thread when an Upstox access token is available.
Connects to the V3 feed, subscribes to indices + the resolvable subset of
NIFTY 100 in "ltpc" mode (last traded price + close), and pushes every
incoming tick into the same in-process cache used by the yfinance live agent
(`backend.app.agents.live_quotes_agent._cache`).

When no token exists, when the token expires, or when the SDK isn't installed
yet, the agent stays dormant and the yfinance agent keeps the cache warm at
its slower ~5-min cadence. The `/api/quotes` endpoint doesn't care which
source produced a given symbol's last price.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

from . import auth as upstox_auth
from . import instruments as upstox_instruments
from ..agents import live_quotes_agent as live_cache

log = logging.getLogger(__name__)

# Single shared state across the process.
_thread: threading.Thread | None = None
_thread_lock = threading.Lock()
_stop_event = threading.Event()
_status: dict = {"connected": False, "last_tick_at": None, "subscribed": 0, "last_error": None}


def status() -> dict:
    return dict(_status)


def _on_tick(symbol: str, ltp: float) -> None:
    if ltp is None or ltp <= 0:
        return
    with live_cache._cache_lock:
        live_cache._cache[symbol] = (float(ltp), datetime.utcnow())
    _status["last_tick_at"] = datetime.utcnow().isoformat() + "Z"


def _extract_ticks(message: object, key_to_symbol: dict[str, str]) -> int:
    """Pull (symbol, ltp) pairs out of one decoded SDK message.

    The SDK gives back a dict-like object; the precise field shape varies
    across versions, so we defensively probe a few likely paths.
    """
    if message is None:
        return 0
    n = 0

    feeds = None
    if isinstance(message, dict):
        feeds = message.get("feeds")
    if feeds is None and hasattr(message, "feeds"):
        feeds = getattr(message, "feeds")
    if not feeds:
        return 0

    items = feeds.items() if hasattr(feeds, "items") else []
    for instr_key, payload in items:
        symbol = key_to_symbol.get(instr_key)
        if not symbol:
            continue
        ltp = None
        if isinstance(payload, dict):
            ltp = (
                payload.get("ltpc", {}).get("ltp")
                or payload.get("ltp")
                or payload.get("last_traded_price")
            )
        else:
            ltp = getattr(payload, "ltp", None)
            if ltp is None and hasattr(payload, "ltpc"):
                ltp = getattr(payload.ltpc, "ltp", None)
        try:
            ltp_f = float(ltp) if ltp is not None else None
        except (TypeError, ValueError):
            ltp_f = None
        if ltp_f:
            _on_tick(symbol, ltp_f)
            n += 1
    return n


def _run_loop() -> None:
    """Connect, subscribe, and pump messages. Auto-reconnects with backoff."""
    backoff = 5.0
    while not _stop_event.is_set():
        token = upstox_auth.get_active_token()
        if not token:
            _status["connected"] = False
            _status["last_error"] = "no active token"
            time.sleep(15)
            continue

        try:
            import upstox_client  # type: ignore
        except ImportError as e:
            _status["last_error"] = f"upstox-python-sdk not installed: {e}"
            log.warning("upstox.ws: SDK import failed; staying dormant")
            time.sleep(60)
            continue

        symbol_map = upstox_instruments.build_symbol_map()
        if len(symbol_map) < 3:
            _status["last_error"] = "instrument map empty"
            time.sleep(60)
            continue

        instrument_keys = list(symbol_map.values())
        key_to_symbol = {v: k for k, v in symbol_map.items()}
        _status["subscribed"] = len(instrument_keys)

        try:
            streamer = upstox_client.MarketDataStreamerV3(
                upstox_client.ApiClient(
                    configuration=upstox_client.Configuration(access_token=token)
                ),
                instrumentKeys=instrument_keys,
                mode="ltpc",
            )

            def on_open():
                _status["connected"] = True
                _status["last_error"] = None
                log.info("upstox.ws: connected, subscribed to %d instruments", len(instrument_keys))

            def on_message(message):
                try:
                    _extract_ticks(message, key_to_symbol)
                except Exception:
                    log.exception("upstox.ws: tick decode failed")

            def on_error(error):
                _status["last_error"] = str(error)
                log.warning("upstox.ws: %s", error)

            def on_close():
                _status["connected"] = False
                log.info("upstox.ws: connection closed")

            streamer.on("open", on_open)
            streamer.on("message", on_message)
            streamer.on("error", on_error)
            streamer.on("close", on_close)
            streamer.connect()

            # Block on the streamer until stop or disconnect.
            while not _stop_event.is_set() and _status["connected"]:
                time.sleep(1.0)

            try:
                streamer.disconnect()
            except Exception:
                pass

            backoff = 5.0  # reset on a clean cycle
        except Exception as e:
            _status["connected"] = False
            _status["last_error"] = repr(e)
            log.exception("upstox.ws: streamer crashed")

        if _stop_event.is_set():
            break
        sleep_for = min(backoff, 60.0)
        log.info("upstox.ws: reconnecting in %.0fs", sleep_for)
        time.sleep(sleep_for)
        backoff = min(backoff * 2, 60.0)


def start() -> None:
    """Spawn the WS worker thread if it's not already alive."""
    global _thread
    if not upstox_auth.is_configured():
        log.info("upstox.ws: not configured, skipping start")
        return
    with _thread_lock:
        if _thread and _thread.is_alive():
            return
        _stop_event.clear()
        _thread = threading.Thread(target=_run_loop, name="upstox-ws", daemon=True)
        _thread.start()


def stop() -> None:
    _stop_event.set()
