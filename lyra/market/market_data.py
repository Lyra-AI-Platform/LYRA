"""Price history for tickers and the CBOE VIX, plus the derived
volatility/momentum statistics the Tremor Index feeds on."""
import json
import logging
import math
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from lyra.market.config import MAX_DATA_AGE_DAYS
from lyra.market.fetch import fetch_text

logger = logging.getLogger(__name__)

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{s}?range={r}&interval=1d"
PRICE_PROVIDER = "Yahoo Finance (daily close, delayed)"


def parse_yahoo_chart(body: str) -> List[Dict]:
    data = json.loads(body)["chart"]["result"][0]
    quote = data["indicators"]["quote"][0]
    bars = []
    for ts, close, vol in zip(data.get("timestamp", []), quote.get("close", []), quote.get("volume", [])):
        if close is not None:
            bars.append({"ts": float(ts), "close": float(close), "volume": float(vol or 0)})
    return bars


async def get_history(symbol: str, range_: str = "1y") -> List[Dict]:
    """Daily bars, oldest first: [{"ts", "close", "volume"}]. Empty (and logged) if the source fails."""
    body = await fetch_text(YAHOO_CHART.format(s=symbol.replace("^", "%5E"), r=range_), max_age=1800)
    if body:
        try:
            bars = parse_yahoo_chart(body)
            if bars:
                return bars
        except (KeyError, IndexError, TypeError, ValueError):
            pass
    logger.warning(f"Price history for {symbol} unavailable from {PRICE_PROVIDER}")
    return []


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def history_status(bars: List[Dict], now: Optional[float] = None) -> Dict:
    """ok / stale / failed for a price series, with the date of the latest close."""
    if not bars:
        return {"status": "failed", "provider": PRICE_PROVIDER, "detail": "no price data returned"}
    age_days = ((now or time.time()) - bars[-1]["ts"]) / 86400
    return {"status": "stale" if age_days > MAX_DATA_AGE_DAYS else "ok", "provider": PRICE_PROVIDER,
            "as_of": _day(bars[-1]["ts"]), "delayed": True}


def _returns(closes: List[float]) -> List[float]:
    return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)) if closes[i - 1] > 0]


def _stdev(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def price_stats(bars: List[Dict]) -> Dict:
    """Momentum, trend, drawdown, realised volatility and volume anomaly."""
    if len(bars) < 25:
        return {}
    closes = [b["close"] for b in bars]
    vols = [b["volume"] for b in bars]
    price = closes[-1]
    rets = _returns(closes)
    sma50 = sum(closes[-50:]) / len(closes[-50:])
    high = max(closes[-252:])
    recent_vol = sum(vols[-5:]) / 5
    base = vols[-65:-5] or vols[:-5]
    base_mean = sum(base) / len(base) if base else 0
    base_sd = _stdev(base)
    return {
        "price": price,
        "return_5d": price / closes[-6] - 1,
        "return_20d": price / closes[-21] - 1,
        "vs_sma50": price / sma50 - 1 if sma50 else 0,
        "drawdown": 1 - price / high if high else 0,
        "realized_vol": _stdev(rets[-20:]) * math.sqrt(252),
        "volume_z": (recent_vol - base_mean) / base_sd if base_sd else 0,
        "last_ts": bars[-1]["ts"],
    }


async def get_vix() -> Dict:
    """Current VIX level with its 5-day and 20-day context."""
    bars = await get_history("^VIX", "6mo")
    if len(bars) < 21:
        return {"available": False, "source": history_status(bars)}
    closes = [b["close"] for b in bars]
    level = closes[-1]
    avg = sum(closes[-20:]) / 20
    regime = ("calm" if level < 15 else "normal" if level < 20 else
              "nervous" if level < 30 else "fearful" if level < 40 else "panic")
    return {
        "available": True,
        "level": round(level, 2),
        "change_5d": round(level / closes[-6] - 1, 4),
        "avg_20d": round(avg, 2),
        "percentile_6m": round(sum(1 for c in closes if c <= level) / len(closes), 3),
        "regime": regime,
        "as_of": _day(bars[-1]["ts"]),
        "source": history_status(bars),
        "history": [{"ts": b["ts"], "close": round(b["close"], 2)} for b in bars[-60:]],
    }


def price_on_or_after(bars: List[Dict], ts: float) -> Optional[float]:
    for b in bars:
        if b["ts"] >= ts:
            return b["close"]
    return None
