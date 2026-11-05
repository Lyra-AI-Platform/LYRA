"""Grouping the same story from different outlets. No database or network here.

Two headlines are one story when most of their meaningful words match and they ran within two
days of each other. It's word overlap, not meaning, so a story in another language starts its
own cluster. A cluster's id is the id of the first article in it.
"""
import re
from typing import Dict, Iterable, List, Optional, Set, Tuple

SIMILAR = 0.55              # share of the shorter headline's words that must match
WINDOW = 48 * 3600          # a story older than this starts a new cluster
MIN_WORDS = 4               # shorter headlines are too vague to match on
COMMON = 3000               # a word in more clusters than this says nothing about which story it is
BREAKING_OUTLETS = 3
BREAKING_WINDOW = 15 * 60

STOP = set("""the and for with from into over under after before about amid says said say new how why what when who
will would could should than then that this these those has have had was were are its his her their they you your
not but out off more most some all any one two here live update updates report reports news video watch""".split())

_WORD = re.compile(r"[^\W\d_]{3,}|\d{2,}", re.UNICODE)
_PUBLISHER_TAIL = re.compile(r"\s+[-–—|]\s+[^-–—|]{2,40}$")


def words(title: str) -> Set[str]:
    """The words that identify a headline, without the " - Publisher" many feeds add."""
    return {w for w in _WORD.findall(_PUBLISHER_TAIL.sub("", title or "").lower()) if w not in STOP}


def similarity(a: Set[str], b: Set[str]) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def outlet(source: str) -> str:
    source = (source or "").strip().lower()
    return source[4:] if source.startswith("www.") else source


def breaking_time(first_seen: Iterable[float]) -> Optional[float]:
    """When a story broke: the moment the 3rd distinct outlet ran it within 15 minutes of the first
    of those three. Takes each outlet's earliest time. None if that never happened."""
    times = sorted(first_seen)
    need = BREAKING_OUTLETS - 1
    for i in range(len(times) - need):
        if times[i + need] - times[i] <= BREAKING_WINDOW:
            return times[i + need]
    return None


class ClusterIndex:
    """Recent stories in memory, so tagging 16,000 articles a day needs no pairwise search."""

    def __init__(self):
        self.stories: Dict[str, Tuple[Set[str], float]] = {}
        self.by_word: Dict[str, Set[str]] = {}

    def find(self, title_words: Set[str], when: float) -> Optional[str]:
        if len(title_words) < MIN_WORDS:
            return None
        counts: Dict[str, int] = {}
        for w in title_words:
            ids = self.by_word.get(w, ())
            if len(ids) > COMMON:
                continue
            for cid in ids:
                counts[cid] = counts.get(cid, 0) + 1
        best, best_score = None, 0.0
        for cid, n in counts.items():
            if n < 2:
                continue
            seen_words, last = self.stories[cid]
            if abs(when - last) > WINDOW:
                continue
            score = similarity(title_words, seen_words)
            if score >= SIMILAR and score > best_score:
                best, best_score = cid, score
        return best

    def remember(self, cid: str, title_words: Set[str], when: float) -> None:
        old = self.stories.get(cid)
        self.stories[cid] = (old[0] if old else title_words, max(when, old[1]) if old else when)
        if not old:
            for w in title_words:
                self.by_word.setdefault(w, set()).add(cid)

    def forget_before(self, cutoff: float) -> None:
        for cid in [c for c, (_, last) in self.stories.items() if last < cutoff]:
            for w in self.stories.pop(cid)[0]:
                ids = self.by_word.get(w)
                if ids:
                    ids.discard(cid)
                    if not ids:
                        del self.by_word[w]


def importance(outlets: int, velocity: float, people: int, tickers: int, breaking: bool) -> float:
    """How much a cluster matters right now, 0 to 100: mostly how many separate outlets carry it,
    then how fast it's spreading, then who it's about."""
    breadth = min(outlets, 20) / 20 * 50
    speed = min(velocity, 10) / 10 * 25
    prominence = min(people * 6 + tickers * 4, 15)
    return round(breadth + speed + prominence + (10 if breaking else 0), 1)


def channels_for(topics: List[str], people: List[str], tickers: List[str]) -> List[str]:
    """Which Live tabs a story belongs on, as well as "everything"."""
    out = list(topics)
    if people:
        out.append("people")
    if tickers or "markets" in topics:
        out.append("markets")
    return sorted(set(out))
