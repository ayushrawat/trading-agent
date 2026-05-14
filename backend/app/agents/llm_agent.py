from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from openai import OpenAI

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


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    # strip ```json ... ``` fences if a model adds them
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


def run_llm_agent() -> int:
    """Run rule engine, hand candidates+news to the LLM, persist suggestions.

    Provider-agnostic: uses any OpenAI-compatible endpoint via base_url.
    Defaults target Gemini 2.5 Flash on Google AI Studio.
    """
    candidates = run_signal_agent()
    if not candidates:
        log.info("llm_agent: no candidates, skipping")
        return 0

    candidates_by_symbol = {c["symbol"]: c for c in candidates}

    if not settings.llm_api_key:
        log.warning("llm_agent: LLM_API_KEY missing — saving raw candidates without LLM ranking")
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
        return _persist(fallback, candidates_by_symbol)

    client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
    news = _recent_news()
    user_prompt = _build_user_prompt(candidates, news)

    # Gemini 2.5 Flash includes "thinking" tokens by default which eat into
    # max_tokens. Disable via reasoning_effort='none' (Gemini honours this;
    # other OpenAI-compatible providers either ignore it or error — fall back
    # to a call without it on error).
    common_kwargs = dict(
        model=settings.llm_model,
        max_tokens=1500,
        temperature=0.3,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    try:
        resp = client.chat.completions.create(reasoning_effort="none", **common_kwargs)
    except TypeError:
        resp = client.chat.completions.create(**common_kwargs)
    except Exception as e:
        log.exception("llm_agent: %s call failed: %s", settings.llm_model, e)
        return 0

    text = (resp.choices[0].message.content or "").strip()
    parsed = _parse_json(text)
    if parsed is None:
        log.warning("llm_agent: failed to parse JSON: %s", text[:200])
        return 0

    suggestions = parsed.get("suggestions", [])
    log.info("llm_agent: %d suggestion(s) from %s", len(suggestions), settings.llm_model)
    return _persist(suggestions, candidates_by_symbol)
