"""Stories and stress jumps as Live events, and who to email about them. No outside calls here."""
import time
from typing import Dict, Iterable, List, Optional

VERSION = 2   # EVENT_VERSION in lyra/watch/live.py


def _event(**fields) -> Dict:
    base = {"v": VERSION, "ts": time.time(), "feed": "", "feed_slug": "", "source": "", "people": [], "companies": [],
            "moves": [], "topics": [], "platform": "", "tone": "neutral"}
    return {**base, **fields}


def breaking_event(cluster: Dict) -> Dict:
    return _event(id=f"breaking:{cluster['id']}", published=cluster["breaking_at"], feed=f"{cluster['outlets']} outlets reporting",
                  title=cluster["title"], url=cluster["url"], source=cluster.get("source", ""), kind="breaking",
                  people=[{"name": p, "slug": "", "id": "", "job": "", "popularity": None} for p in cluster["people"]],
                  companies=[{"name": t, "ticker": t} for t in cluster["tickers"]], topics=cluster["topics"], cluster=cluster["id"])


def spike_event(ticker: str, name: str, before: int, now: int, stories: Iterable[Dict]) -> Dict:
    """A company's stress jumped. It runs like breaking news, with the headlines that caused it."""
    top: List[Dict] = list(stories)[:3]
    lead = top[0] if top else {}
    return _event(id=f"spike:{ticker}:{int(time.time() // 3600)}", published=time.time(), feed=name, tone="negative",
                  title=f"Tremor spike: {name} stress jumped from {before} to {now}", kind="tremor_spike",
                  url=lead.get("url", ""), source=lead.get("source", ""), companies=[{"name": name, "ticker": ticker}],
                  spike={"ticker": ticker, "before": before, "now": now},
                  headlines=[{"title": c["title"], "url": c["url"]} for c in top])


def matches(follow: Dict, cluster: Dict) -> bool:
    """Does a story belong to something a person follows?"""
    kind, value = follow["kind"], follow["value"]
    if kind == "person":
        return value in cluster["people"]
    if kind == "company":
        return value in cluster["tickers"]
    if kind == "topic":
        return value in cluster["topics"]
    return value.lower() in cluster["title"].lower()


def spike_matches(follow: Dict, ticker: str) -> bool:
    return follow["kind"] == "company" and follow["value"] == ticker


def may_alert(follow: Dict, now: float, every: float = 3600) -> bool:
    """Emails stay rare: one per follow per hour, however busy the news is."""
    return bool(follow.get("alerts")) and now - (follow.get("last_alert") or 0) >= every


def rank_live(clusters: List[Dict], spikes: List[Dict], limit: int) -> List[Dict]:
    """Spikes first while they're fresh, then stories by importance."""
    return (sorted(spikes, key=lambda e: -e["ts"])[:3] + clusters)[:limit]


def viewers_online(seen: Dict[str, float], now: Optional[float] = None, within: float = 120) -> int:
    now = now or time.time()
    for key in [k for k, t in seen.items() if now - t > within]:
        del seen[key]
    return len(seen)
