from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Optional

import pandas as pd

from ..db import SessionLocal
from ..models import MarketBar
from ..universe import NIFTY_100

log = logging.getLogger(__name__)


@dataclass
class Candidate:
    symbol: str
    name: str  # human-readable company name, helps LLM match news to ticker
    direction: str  # LONG or SHORT
    entry: float
    stop: float
    target: float
    confidence: float  # 0..1
    signals: list[str]
    last_close: float
    indicators: dict
    # Backtest: hit rate of this rule combo in this direction on this stock
    # over the past ~12 months. None when insufficient history.
    hit_rate: Optional[float] = None
    hit_rate_sample: int = 0


@dataclass
class _Indicators:
    rsi: pd.Series
    macd: pd.Series
    macd_signal: pd.Series
    sma20: pd.Series
    sma50: pd.Series
    atr: pd.Series


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def _macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return macd, signal, hist


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _compute_indicators(df: pd.DataFrame) -> _Indicators:
    close = df["close"]
    macd_line, signal_line, _hist = _macd(close)
    return _Indicators(
        rsi=_rsi(close),
        macd=macd_line,
        macd_signal=signal_line,
        sma20=close.rolling(20).mean(),
        sma50=close.rolling(50).mean(),
        atr=_atr(df["high"], df["low"], close),
    )


def _load_bars(symbol: str) -> pd.DataFrame:
    with SessionLocal() as db:
        rows = (
            db.query(MarketBar)
            .filter(MarketBar.symbol == symbol)
            .order_by(MarketBar.ts.asc())
            .all()
        )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(
        [{
            "ts": r.ts,
            "open": r.open,
            "high": r.high,
            "low": r.low,
            "close": r.close,
            "volume": r.volume,
        } for r in rows]
    )
    df = df.set_index("ts").dropna(subset=["close"])
    return df


def _vote_at(close: pd.Series, ind: _Indicators, i: int) -> tuple[Optional[str], list[str], int, float, Optional[float]]:
    """Run the weighted vote using indicator values at row index i.
    Returns (direction, signals, winning_weight, last_close, atr).
    direction is None on no-signal / tie.
    """
    n = len(close)
    if i < 0:
        i = n + i
    if i <= 0 or i >= n:
        return None, [], 0, float(close.iloc[-1]) if n else 0.0, None

    rsi = ind.rsi.iloc[i]
    macd_now = ind.macd.iloc[i]
    macd_prev = ind.macd.iloc[i - 1] if i >= 1 else pd.NA
    sig_now = ind.macd_signal.iloc[i]
    sig_prev = ind.macd_signal.iloc[i - 1] if i >= 1 else pd.NA
    sma20 = ind.sma20.iloc[i]
    sma50 = ind.sma50.iloc[i]
    atr = ind.atr.iloc[i]
    last_close = float(close.iloc[i])

    long_w, short_w = 0, 0
    long_signals: list[str] = []
    short_signals: list[str] = []

    if pd.notna(rsi):
        if rsi < 45:
            long_w += 1
            long_signals.append(f"RSI tilt long ({rsi:.1f})")
        elif rsi > 55:
            short_w += 1
            short_signals.append(f"RSI tilt short ({rsi:.1f})")

    if pd.notna(macd_now) and pd.notna(sig_now):
        bullish_cross = pd.notna(macd_prev) and pd.notna(sig_prev) and macd_prev <= sig_prev and macd_now > sig_now
        bearish_cross = pd.notna(macd_prev) and pd.notna(sig_prev) and macd_prev >= sig_prev and macd_now < sig_now
        if macd_now > sig_now:
            long_w += 1
            long_signals.append("MACD above signal (bullish crossover)" if bullish_cross else "MACD above signal")
        elif macd_now < sig_now:
            short_w += 1
            short_signals.append("MACD below signal (bearish crossover)" if bearish_cross else "MACD below signal")

    if pd.notna(sma20) and pd.notna(sma50):
        if sma20 > sma50:
            long_w += 2
            long_signals.append("Uptrend (SMA20 above SMA50)")
        elif sma20 < sma50:
            short_w += 2
            short_signals.append("Downtrend (SMA20 below SMA50)")

    if pd.notna(sma20):
        if last_close > sma20:
            long_w += 1
            long_signals.append("Price above SMA20")
        elif last_close < sma20:
            short_w += 1
            short_signals.append("Price below SMA20")

    atr_val = float(atr) if pd.notna(atr) else None

    if long_w == short_w:  # covers 0/0 and any equal-weight tie
        return None, [], 0, last_close, atr_val
    if long_w > short_w:
        return "LONG", long_signals, long_w, last_close, atr_val
    return "SHORT", short_signals, short_w, last_close, atr_val


def _backtest_hit_rate(
    df: pd.DataFrame,
    ind: _Indicators,
    current_direction: str,
    lookforward: int = 5,
) -> tuple[Optional[float], int]:
    """Replay the rule engine on every historical day in df. For each day a
    signal fires matching `current_direction`, simulate the trade forward
    `lookforward` bars. Pessimistic on same-bar collisions (stop wins).
    Unresolved signals (neither hit) are excluded from the sample.
    Returns (hit_rate, sample_size). hit_rate is None when sample is 0.
    """
    close = df["close"]
    high = df["high"]
    low = df["low"]
    n = len(df)
    start = 60  # need indicators warmed up
    end = n - lookforward
    if end <= start:
        return None, 0

    wins = 0
    resolved = 0
    for i in range(start, end):
        direction, _sigs, _w, last_close, atr = _vote_at(close, ind, i)
        if direction != current_direction or atr is None or atr <= 0:
            continue

        if direction == "LONG":
            stop = last_close - 1.5 * atr
            target = last_close + 2.5 * atr
        else:
            stop = last_close + 1.5 * atr
            target = last_close - 2.5 * atr

        outcome: Optional[str] = None
        for j in range(i + 1, i + 1 + lookforward):
            bar_high = high.iloc[j]
            bar_low = low.iloc[j]
            if pd.isna(bar_high) or pd.isna(bar_low):
                continue
            if direction == "LONG":
                if bar_low <= stop:  # pessimistic: stop checked first
                    outcome = "loss"
                    break
                if bar_high >= target:
                    outcome = "win"
                    break
            else:  # SHORT
                if bar_high >= stop:
                    outcome = "loss"
                    break
                if bar_low <= target:
                    outcome = "win"
                    break

        if outcome is None:
            continue  # neither hit in the window — exclude from sample
        resolved += 1
        if outcome == "win":
            wins += 1

    if resolved == 0:
        return None, 0
    return round(wins / resolved, 3), resolved


def _evaluate(symbol: str, name: str, df: pd.DataFrame) -> Optional[Candidate]:
    if len(df) < 60:
        return None

    ind = _compute_indicators(df)
    close = df["close"]
    direction, signals, win_w, last_close, atr = _vote_at(close, ind, len(df) - 1)
    if direction is None or atr is None or atr <= 0:
        return None

    # max possible weight per side = 1 (RSI) + 1 (MACD) + 2 (SMA trend) + 1 (price vs SMA20) = 5
    confidence = round(win_w / 5.0, 2)

    if direction == "LONG":
        stop = last_close - 1.5 * atr
        target = last_close + 2.5 * atr
    else:
        stop = last_close + 1.5 * atr
        target = last_close - 2.5 * atr

    hit_rate, hit_rate_sample = _backtest_hit_rate(df, ind, direction, lookforward=5)

    return Candidate(
        symbol=symbol,
        name=name,
        direction=direction,
        entry=round(last_close, 2),
        stop=round(stop, 2),
        target=round(target, 2),
        confidence=confidence,
        signals=signals,
        last_close=last_close,
        indicators={
            "rsi": None if pd.isna(ind.rsi.iloc[-1]) else round(float(ind.rsi.iloc[-1]), 2),
            "macd": None if pd.isna(ind.macd.iloc[-1]) else round(float(ind.macd.iloc[-1]), 3),
            "macd_signal": None if pd.isna(ind.macd_signal.iloc[-1]) else round(float(ind.macd_signal.iloc[-1]), 3),
            "sma20": None if pd.isna(ind.sma20.iloc[-1]) else round(float(ind.sma20.iloc[-1]), 2),
            "sma50": None if pd.isna(ind.sma50.iloc[-1]) else round(float(ind.sma50.iloc[-1]), 2),
            "atr": round(float(atr), 2),
        },
        hit_rate=hit_rate,
        hit_rate_sample=hit_rate_sample,
    )


def run_signal_agent() -> list[dict]:
    """Run the rule engine on every stock in the universe. Returns candidates
    sorted by descending raw confidence (caller usually trims to top N before
    handing to the LLM)."""
    candidates: list[Candidate] = []
    for ticker, name, _yf in NIFTY_100:
        df = _load_bars(ticker)
        if df.empty:
            continue
        c = _evaluate(ticker, name, df)
        if c is not None:
            candidates.append(c)
    candidates.sort(key=lambda c: c.confidence, reverse=True)
    log.info("signal_agent: %d candidates (top conf %.2f)",
             len(candidates), candidates[0].confidence if candidates else 0.0)
    return [asdict(c) for c in candidates]
