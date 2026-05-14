from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from anthropic import Anthropic

from ..config import settings
from ..db import SessionLocal
from ..models import NewsArticle, TradeSuggestion
from .signal_agent import run_signal_agent

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a disciplined Indian-markets trading analyst supporting a retail trader.
You receive (a) rule-based technical candidates for NIFTY and SENSEX and (b) recent financial news headlines.
Your job is to keep, drop, or adjust each candidate based on whether the news flow supports or contradicts the technical setup, and to write a short, plain-English rationale.

Rules:
- Only output trades you would actually take. If news strongly contradicts the technical setup, drop the candidate.
- Confidence is a float 0..1. Be conservative — 0.8+ requires strong agreement between technicals AND news.
- Rationale must be 1-2 sentences and cite which news_id(s) influenced the call when relevant.
- Never invent numbers. Use the entry/stop/target from the candidate unless news justifies an adjustment, in which case keep changes small.
- Output STRICT JSON only — no markdown, no prose outside the JSON object.

Output schema:
{
  "suggestions": [
    {
      "symbol": "NIFTY" | "SENSEX",
      "direction": "LONG" | "SHORT",
      "entry": number,
      "stop": number,
      "target": number,
      "confidence": number,
      "rationale": string,
      "news_refs": [number, ...]
    }
  ]
}
If you would drop all candidates, return {"suggestions": []}."""


def _recent_news(limit: int = 30) -> list[NewsArticle]:
    cutoff = datetime.utcnow() - timedelta(hours=36)
    with SessionLocal() as db:
        return (
            db.query(NewsArticle)
            .filter(NewsArticle.published_at >= cutoff)
            .order_by(NewsArticle.published_at.desc())
            .limit(limit)
            .all()
        )


def _build_user_prompt(candidates: list[dict], news: list[NewsArticle]) -> str:
    news_payload = [
        {
            "news_id": a.id,
            "source": a.source,
            "title": a.title,
            "published_at": a.published_at.isoformat(),
        }
        for a in news
    ]
    return json.dumps(
        {
            "candidates": candidates,
            "news": news_payload,
            "as_of": datetime.utcnow().isoformat(),
        },
        indent=2,
    )


def _persist(suggestions: list[dict], candidates_by_symbol: dict[str, dict]) -> int:
    saved = 0
    with SessionLocal() as db:
        for s in suggestions:
            symbol = s.get("symbol")
            cand = candidates_by_symbol.get(symbol, {})
            row = TradeSuggestion(
                symbol=symbol,
                direction=s.get("direction", "LONG"),
                entry=float(s.get("entry") or 0) or None,
                stop=float(s.get("stop") or 0) or None,
                target=float(s.get("target") or 0) or None,
                confidence=float(s.get("confidence") or 0),
                timeframe="intraday/swing",
                rationale=s.get("rationale", "")[:4000],
                signals_json=json.dumps(cand.get("signals", [])),
                news_refs_json=json.dumps(s.get("news_refs", [])),
            )
            db.add(row)
            saved += 1
        db.commit()
    return saved


def run_llm_agent() -> int:
    """Run rule engine, hand candidates+news to Claude, persist final suggestions."""
    candidates = run_signal_agent()
    if not candidates:
        log.info("llm_agent: no candidates, skipping")
        return 0
    if not settings.anthropic_api_key:
        log.warning("llm_agent: ANTHROPIC_API_KEY missing — saving raw candidates without LLM ranking")
        # graceful fallback: persist candidates as-is
        fallback = [{
            "symbol": c["symbol"],
            "direction": c["direction"],
            "entry": c["entry"],
            "stop": c["stop"],
            "target": c["target"],
            "confidence": c["confidence"],
            "rationale": "Technical setup only (no LLM key configured): " + ", ".join(c["signals"]),
            "news_refs": [],
        } for c in candidates]
        return _persist(fallback, {c["symbol"]: c for c in candidates})

    client = Anthropic(api_key=settings.anthropic_api_key)
    news = _recent_news()
    user_prompt = _build_user_prompt(candidates, news)

    try:
        resp = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=1500,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as e:
        log.exception("llm_agent: Claude call failed: %s", e)
        return 0

    text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # try to extract JSON object substring
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            log.warning("llm_agent: non-JSON response: %s", text[:200])
            return 0
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            log.warning("llm_agent: failed to parse JSON: %s", text[:200])
            return 0

    suggestions = parsed.get("suggestions", [])
    return _persist(suggestions, {c["symbol"]: c for c in candidates})
