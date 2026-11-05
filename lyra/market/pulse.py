"""How stressed a company looks, in plain English. Everything here is arithmetic and wording on
data already stored, so Newswire, Tremor, Live and Watch can all show the same thing.

Stress is the Tremor chance of a big move either way (boom + bust), shown as 0 to 100 and
capped. It's a level for comparing companies, not a probability, and the pages say so.
"""
import re
from typing import Dict, Iterable, List, Optional, Tuple

from lyra.market import sentiment
from lyra.newswire import config as C

CALM_BELOW, HIGH_FROM = 55, 70
SPIKE_POINTS = 15           # a jump this big between readings goes on Live as a Tremor spike

# Sectors people search for, and the companies behind each one's stress dot.
SECTORS: Dict[str, Tuple[str, List[str]]] = {
    "semiconductors": ("Semiconductors", ["NVDA", "AMD", "INTC", "TSM", "ASML", "AVGO", "QCOM", "MU", "AMAT"]),
    "ai": ("AI", ["NVDA", "MSFT", "GOOGL", "META", "PLTR", "ORCL", "CRM"]),
    "chemicals": ("Chemistry", ["DOW", "LYB", "DD", "BASFY", "LIN", "APD", "ALB", "EMN", "CE"]),
    "pharma": ("Pharma", ["PFE", "MRNA", "LLY", "NVO", "MRK", "AZN", "JNJ", "ABBV", "GSK"]),
    "energy": ("Energy", ["XOM", "CVX", "SHEL", "BP", "TTE", "COP", "OXY", "SLB"]),
    "central-banks": ("Central banks", ["JPM", "GS", "MS", "BLK"]),
    "politics": ("Politics", ["LMT", "RTX", "NOC", "BA"]),
    "trade-policy": ("Tariffs & sanctions", ["AAPL", "TSLA", "NVDA", "BA", "WMT"]),
    "markets": ("Markets", ["AAPL", "MSFT", "AMZN", "GOOGL", "JPM", "BRK-B"]),
}
SECTOR_WORDS = {"chip": "semiconductors", "chips": "semiconductors", "chipmakers": "semiconductors", "semiconductor": "semiconductors",
                "artificial intelligence": "ai", "chemical": "chemicals", "chemicals": "chemicals", "chemistry": "chemicals",
                "drug": "pharma", "drugs": "pharma", "pharmaceutical": "pharma", "oil": "energy", "gas": "energy",
                "banks": "central-banks", "fed": "central-banks", "interest rates": "central-banks", "tariffs": "trade-policy",
                "tariff": "trade-policy", "sanctions": "trade-policy"}


def level(stress: Optional[float]) -> str:
    if stress is None:
        return "unknown"
    return "calm" if stress < CALM_BELOW else "rising" if stress < HIGH_FROM else "high"


def stress_of(p_boom: float, p_bust: float) -> int:
    return int(round(min(1.0, max(0.0, p_boom + p_bust)) * 100))


def resolve(query: str) -> Optional[Dict]:
    """What a search means: {"kind": "company", ticker, name}, {"kind": "sector", ...} or None."""
    q = " ".join((query or "").split())
    if not q or len(q) > 60:
        return None
    low = q.lower()
    for name, ticker in C.COMPANIES.items():
        if low == name.lower() or q.upper() == ticker:
            return {"kind": "company", "ticker": ticker, "name": name}
    if re.fullmatch(r"\$?[A-Z]{1,5}", q) and q.lstrip("$") not in C.BLOCKED_TICKERS and q.lstrip("$") in set(C.COMPANIES.values()):
        return {"kind": "company", "ticker": q.lstrip("$"), "name": q.lstrip("$")}
    for name, ticker in C.COMPANIES.items():
        if len(low) >= 3 and name.lower().startswith(low):
            return {"kind": "company", "ticker": ticker, "name": name}
    key = SECTOR_WORDS.get(low) or next((k for k, (label, _) in SECTORS.items() if low in (k, label.lower())), None)
    if key:
        return {"kind": "sector", "topic": key, "name": SECTORS[key][0], "tickers": SECTORS[key][1]}
    return None


def sector_stress(topic: str, stresses: Dict[str, Dict]) -> Dict:
    """The average of the sector's companies that have a reading."""
    label, tickers = SECTORS[topic]
    known = [stresses[t]["stress"] for t in tickers if t in stresses]
    value = round(sum(known) / len(known)) if known else None
    return {"topic": topic, "name": label, "stress": value, "level": level(value), "companies_read": len(known)}


def _flow(value: Optional[float]) -> str:
    if value is None or abs(value) < 0.1:
        return ""
    return "buying" if value > 0 else "selling"


def plain_english(name: str, reading: Optional[Dict], vix: Optional[Dict]) -> str:
    """The one-paragraph summary on a Tremor card, with only what the data supports."""
    if not reading:
        return f"{name} has no recent Tremor reading yet."
    f = reading.get("features") or {}
    parts = [f"{name} stress is {level(reading['stress'])} at {reading['stress']}."]
    if _flow(f.get("insider_flow")):
        parts.append(f"Company insiders have been {_flow(f['insider_flow'])}.")
    if _flow(f.get("congress_flow")):
        parts.append(f"Politicians have been {_flow(f['congress_flow'])}.")
    if abs(f.get("news_sentiment") or 0) >= 0.1:
        parts.append(f"The news has turned {'positive' if f['news_sentiment'] > 0 else 'negative'}.")
    if vix and vix.get("available"):
        parts.append(f"The VIX is {vix['level']:.1f} ({vix.get('regime', '')}).".replace(" ()", ""))
    return " ".join(parts)


def tone(text: str) -> float:
    return sentiment.score(text)


# Which stories stand behind each Tremor signal. Trades come from filings, so only signals
# that are about the coverage can link to articles.
_SIGNAL_WORDS = {"insider_flow": ("insider", "form 4", "stake"), "congress_flow": ("senator", "congress", "lawmaker", "politician")}


def stories_behind(factor: str, value: float, clusters: Iterable[Dict], limit: int = 3) -> List[Dict]:
    rows = list(clusters)
    if factor in ("news_sentiment", "news_buzz"):
        wanted = [c for c in rows if tone(c["title"]) * value > 0]
    elif factor in _SIGNAL_WORDS:
        wanted = [c for c in rows if any(w in c["title"].lower() for w in _SIGNAL_WORDS[factor])]
    else:
        return []
    wanted.sort(key=lambda c: (c.get("outlets", 1), c.get("last_seen", 0)), reverse=True)
    return wanted[:limit]


def link_signals(causes: Iterable[Dict], clusters: Iterable[Dict]) -> List[Dict]:
    rows = list(clusters)
    return [{**c, "articles": stories_behind(c["factor"], c.get("value", 0), rows)} for c in causes]


def timeline(hourly: Dict[int, int], readings: List[Dict], spikes: List[Dict], since: float, until: float) -> Dict:
    """Daily news volume and Tremor score on one chart, with headlines pinned at the spikes."""
    day = 86400
    start, end = int(since // day), int(until // day)
    volume = {d: 0 for d in range(start, end + 1)}
    for hour, n in hourly.items():
        d = hour * 3600 // day
        if d in volume:
            volume[d] += n
    score: Dict[int, int] = {}
    for r in sorted(readings, key=lambda x: x["ts"]):
        score[int(r["ts"] // day)] = r["stress"]
    return {"days": [{"ts": d * day, "stories": volume[d], "stress": score.get(d)} for d in sorted(volume)], "pins": spikes}


def is_spike(previous: Optional[int], current: Optional[int]) -> bool:
    return previous is not None and current is not None and current - previous >= SPIKE_POINTS
