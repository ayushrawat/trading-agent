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

SYSTEM_PROMPT = """You are a disciplined Indian-markets equity analyst supporting a retail trader.
You receive (a) rule-based technical candidates across NIFTY 100 stocks and (b) recent financial news headlines.

Each candidate also carries a backtest:
- hit_rate: fraction of times this exact rule combo, firing in this direction on THIS stock, hit target before stop in the past ~12 months. May be null when history is insufficient.
- hit_rate_sample: number of past setups behind that hit_rate. Treat hit_rate with sample < 5 as low-confidence; null hit_rate is neutral, not bad.

Your job: pick the BEST TRADES — those where (a) news flow meaningfully supports the technical setup or at minimum does not contradict it, AND (b) the historical hit rate is not actively bad.

Rules:
- Return at most TOP_N suggestions, ranked best first. Quality over quantity — if only 3 trades are genuinely worth it, return 3.
- Match news to specific stocks by company name. A headline about "Reliance Industries" supports a RELIANCE candidate; sector news ("oil prices surge") supports relevant sector stocks (ONGC, BPCL, HPCL).
- Hit-rate guidance:
  - >= 60% with sample >= 10: strong tailwind, prefer these.
  - 40-60% with decent sample: neutral; rely on news catalyst to break the tie.
  - < 40% with sample >= 10: red flag; only suggest if news catalyst is unusually strong, and call out the low hit rate in the rationale.
  - null or sample < 5: treat as no information, neither positive nor negative.
- BIAS TOWARD LESS-COVERED NAMES. When two candidates have similar technical+news strength, prefer the less obvious one. These names are already on every screener — only suggest them if their setup is exceptional and crystallized by news: RELIANCE, TCS, HDFCBANK, INFY, ICICIBANK, HINDUNILVR, BHARTIARTL, SBIN, BAJFINANCE, ITC, KOTAKBANK, LT, AXISBANK, MARUTI, ASIANPAINT, SUNPHARMA, HCLTECH, TITAN, ULTRACEMCO, WIPRO.
- Confidence is a float 0..1. Reflect both technical+news alignment AND hit_rate. Spread the range: 0.8+ = strong alignment + good hit rate; 0.5-0.7 = decent setup with mixed signals; below 0.5 = drop it.
- Rationale: 1-2 sentences. Cite news_id(s) when news influenced the call. Mention hit_rate when it is notably high (>=60%) or notably low (<40%). If no news directly supports, say so plainly ("Pure technical setup; no direct news catalyst").
- Never invent numbers. Use entry/stop/target from the candidate as-is.
- Output STRICT JSON only — no markdown, no prose outside the JSON object.

Output schema:
{
  "suggestions": [
    {
      "symbol": string,          // ticker as provided in the candidate
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
If no candidate is worth a trade, return {"suggestions": []}."""


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
                hit_rate=cand.get("hit_rate"),
                hit_rate_sample=cand.get("hit_rate_sample"),
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
    all_candidates = run_signal_agent()
    if not all_candidates:
        log.info("llm_agent: no candidates, skipping")
        return 0

    # Trim to the strongest pool by raw rule confidence to keep the prompt
    # focused (and the bill small). The LLM then picks the final TOP_N.
    candidates = all_candidates[: settings.llm_candidate_pool]
    candidates_by_symbol = {c["symbol"]: c for c in candidates}

    if not settings.llm_api_key:
        log.warning("llm_agent: LLM_API_KEY missing — saving top %d raw candidates", settings.llm_top_n)
        fallback = [{
            "symbol": c["symbol"],
            "direction": c["direction"],
            "entry": c["entry"],
            "stop": c["stop"],
            "target": c["target"],
            "confidence": c["confidence"],
            "rationale": f"Technical setup only (no LLM key): {', '.join(c['signals'])}",
            "news_refs": [],
        } for c in candidates[: settings.llm_top_n]]
        return _persist(fallback, candidates_by_symbol)

    client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
    news = _recent_news(limit=40)
    # bake TOP_N into the system prompt so the model honours the cap
    system_prompt = SYSTEM_PROMPT.replace("TOP_N", str(settings.llm_top_n))
    user_prompt = _build_user_prompt(candidates, news)

    # Gemini 2.5 Flash includes "thinking" tokens by default which eat into
    # max_tokens. Disable via reasoning_effort='none' (Gemini honours this;
    # other OpenAI-compatible providers either ignore it or error — fall back
    # to a call without it on error).
    common_kwargs = dict(
        model=settings.llm_model,
        max_tokens=4000,  # higher cap — up to TOP_N suggestions with rationales
        temperature=0.3,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
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
