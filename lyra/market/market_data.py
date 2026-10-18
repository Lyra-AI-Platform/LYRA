"""Price history for tickers and the CBOE VIX, plus the derived
volatility/momentum statistics the Tremor Index feeds on."""
import csv
import io
import json
import math
from typing import Dict, List, Optional

from lyra.market.fetch import fetch_text

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{s}?range={r}&interval=1d"
STOOQ_CSV = "https://stooq.com/q/d/l/?s={s}&i=d"


def parse_yahoo_chart(body: str) -> List[Dict]:
    data = json.loads(body)["chart"]["result"][0]
    quote = data["indicators"]["quote"][0]
    bars = []
    for ts, close, vol in zip(data.get("timestamp", []), quote.get("close", []), quote.get("volume", [])):
        if close is not None:
            bars.append({"ts": float(ts), "close": float(close), "volume": float(vol or 0)})
    return bars


def parse_stooq_csv(body: str) -> List[Dict]:
    from datetime import datetime, timezone
    bars = []
    for row in csv.DictReader(io.StringIO(body)):
        try:
            ts = datetime.strptime(row["Date"], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
            bars.append({"ts": ts, "close": float(row["Close"]), "volume": float(row.get("Volume") or 0)})
        except (KeyError, ValueError):
            continue
    return bars


async def get_history(symbol: str, range_: str = "1y") -> List[Dict]:
    """Daily bars, oldest first: [{"ts", "close", "volume"}]. Yahoo first, Stooq as a fallback."""
    body = await fetch_text(YAHOO_CHART.format(s=symbol.replace("^", "%5E"), r=range_), max_age=1800)
    if body:
        try:
            bars = parse_yahoo_chart(body)
            if bars:
                return bars
        except (KeyError, IndexError, TypeError, ValueError):
            pass
    stooq = symbol.lower() if symbol.startswith("^") else f"{symbol.lower()}.us"
    body = await fetch_text(STOOQ_CSV.format(s=stooq), max_age=1800)
    return parse_stooq_csv(body) if body else []


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
        return {"available": False}
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
        "history": [{"ts": b["ts"], "close": round(b["close"], 2)} for b in bars[-60:]],
    }


def price_on_or_after(bars: List[Dict], ts: float) -> Optional[float]:
    for b in bars:
        if b["ts"] >= ts:
            return b["close"]
    return None
