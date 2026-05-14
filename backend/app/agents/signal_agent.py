from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Optional

import pandas as pd

from ..db import SessionLocal
from ..models import MarketBar

log = logging.getLogger(__name__)


@dataclass
class Candidate:
    symbol: str
    direction: str  # LONG or SHORT
    entry: float
    stop: float
    target: float
    confidence: float  # 0..1
    signals: list[str]
    last_close: float
    indicators: dict


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


def _evaluate(symbol: str, df: pd.DataFrame) -> Optional[Candidate]:
    if len(df) < 60:
        return None

    close = df["close"]
    rsi = _rsi(close).iloc[-1]
    macd, signal, hist = _macd(close)
    macd_now, macd_prev = macd.iloc[-1], macd.iloc[-2]
    sig_now, sig_prev = signal.iloc[-1], signal.iloc[-2]
    sma20 = close.rolling(20).mean().iloc[-1]
    sma50 = close.rolling(50).mean().iloc[-1]
    atr = _atr(df["high"], df["low"], close).iloc[-1]
    last_close = float(close.iloc[-1])

    long_signals: list[str] = []
    short_signals: list[str] = []

    if pd.notna(rsi):
        if rsi < 35:
            long_signals.append(f"RSI oversold ({rsi:.1f})")
        elif rsi > 65:
            short_signals.append(f"RSI overbought ({rsi:.1f})")

    if pd.notna(macd_prev) and pd.notna(sig_prev):
        if macd_prev < sig_prev and macd_now > sig_now:
            long_signals.append("MACD bullish crossover")
        elif macd_prev > sig_prev and macd_now < sig_now:
            short_signals.append("MACD bearish crossover")

    if pd.notna(sma20) and pd.notna(sma50):
        if sma20 > sma50 and last_close > sma20:
            long_signals.append("Price above rising SMA20/50")
        elif sma20 < sma50 and last_close < sma20:
            short_signals.append("Price below falling SMA20/50")

    if not long_signals and not short_signals:
        return None

    if len(long_signals) >= len(short_signals):
        direction = "LONG"
        signals = long_signals
    else:
        direction = "SHORT"
        signals = short_signals

    if len(signals) < 1 or pd.isna(atr) or atr <= 0:
        return None

    confidence = min(1.0, len(signals) / 3.0)

    if direction == "LONG":
        stop = last_close - 1.5 * atr
        target = last_close + 2.5 * atr
    else:
        stop = last_close + 1.5 * atr
        target = last_close - 2.5 * atr

    return Candidate(
        symbol=symbol,
        direction=direction,
        entry=round(last_close, 2),
        stop=round(stop, 2),
        target=round(target, 2),
        confidence=round(confidence, 2),
        signals=signals,
        last_close=last_close,
        indicators={
            "rsi": None if pd.isna(rsi) else round(float(rsi), 2),
            "macd": None if pd.isna(macd_now) else round(float(macd_now), 3),
            "macd_signal": None if pd.isna(sig_now) else round(float(sig_now), 3),
            "sma20": None if pd.isna(sma20) else round(float(sma20), 2),
            "sma50": None if pd.isna(sma50) else round(float(sma50), 2),
            "atr": round(float(atr), 2),
        },
    )


def run_signal_agent() -> list[dict]:
    """Compute rule-based candidates. Returns list of dict candidates."""
    candidates: list[Candidate] = []
    for symbol in ("NIFTY", "SENSEX"):
        df = _load_bars(symbol)
        if df.empty:
            continue
        c = _evaluate(symbol, df)
        if c is not None:
            candidates.append(c)
    log.info("signal_agent: %d candidates", len(candidates))
    return [asdict(c) for c in candidates]
