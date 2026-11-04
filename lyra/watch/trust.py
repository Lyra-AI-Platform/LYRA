"""How far a story can be trusted, worked out from public signals only.

  official   came straight from a government office, court or the person themselves
  confirmed  three or more separate outlets ran it
  rumour     the headline's own wording says it isn't established
  old news   published more than a day before we saw it
  reported   one or two outlets so far

This describes the reporting. It says nothing about whether to act on a story.
"""
import re
from typing import Dict, List, Set

CONFIRMED_SOURCES = 3
SAME_STORY = 0.5                # share of headline words in common
WINDOW = 6 * 3600
STALE = 86400
OFFICIAL_KINDS = ("official", "court", "post")
RUMOUR = re.compile(r"\b(rumou?rs?|reportedly|unconfirmed|speculation|sources say|said to|alleged(ly)?|"
                    r"could|might|may|considering|weighing|in talks)\b|\?\s*$", re.I)
SMALL = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "as", "at", "by", "with", "is", "from"}


def _words(title: str) -> Set[str]:
    return {w for w in re.findall(r"\w+", title.lower()) if w not in SMALL}


def same_story(a: str, b: str) -> bool:
    x, y = _words(a), _words(b)
    return bool(x and y) and len(x & y) / len(x | y) >= SAME_STORY


def assess(event: Dict, events: List[Dict]) -> Dict:
    """{"label", "sources", "first"} for one event, given the events around it."""
    ts = event.get("ts", 0)
    group = [e for e in events if abs(e.get("ts", 0) - ts) <= WINDOW and same_story(e.get("title", ""), event.get("title", ""))]
    group = group or [event]
    outlets = {(e.get("source") or "").lower() for e in group if e.get("source")}
    first = min(group, key=lambda e: e.get("published") or e.get("ts", 0))
    published = event.get("published") or ts
    if ts - published > STALE:
        label = "old news"
    elif event.get("kind") in OFFICIAL_KINDS:
        label = "official"
    elif len(outlets) >= CONFIRMED_SOURCES:
        label = "confirmed"
    elif RUMOUR.search(event.get("title", "")):
        label = "rumour"
    else:
        label = "reported"
    return {"label": label, "sources": len(outlets), "first": first.get("source", "")}


def describe(t: Dict) -> str:
    """One short line for an email or a page."""
    if t["label"] == "confirmed":
        return f"Confirmed by {t['sources']} outlets, first seen at {t['first']}"
    return {"official": "From the original source", "rumour": "Rumour, not confirmed", "old news": "Old story, recirculating",
            "reported": f"Reported by {t['sources'] or 1} outlet{'s' if t['sources'] > 1 else ''}"}[t["label"]]
