"""Companies with unusual activity: the top 10 most likely to make a big move.

The move score is a weighted sum, 0 to 100. It measures unusual activity. It's not a forecast.
  news velocity   35   stories in the last hour against the 7-day hourly average
  outlet breadth  20   separate outlets in 24 h
  Tremor stress   20   how far above neutral (50)
  Tremor change   10   the move over 24 h, either way
  trades          10   recent insider and politician trades from Watch data
  catalysts        5   earnings, FDA or court dates in the next 7 days, when known
"""
from typing import Dict, Iterable, List, Optional

MIN_STORIES_24H = 3
SIZE = 10
HOURS_IN_WEEK = 168


def velocity(a: Dict) -> float:
    """How many times busier than usual. The floor stops a first story reading as a huge surge."""
    return a["last_hour"] / max(a["week"] / HOURS_IN_WEEK, 0.25)


def move_score(a: Dict, stress: Optional[Dict], trades: int = 0, catalysts: int = 0) -> int:
    v = min(velocity(a), 10) / 10 * 35
    breadth = min(a["outlets"], 30) / 30 * 20
    level = max(((stress or {}).get("stress") or 50) - 50, 0) / 50 * 20
    change = min(abs((stress or {}).get("change_24h") or 0), 20) / 20 * 10
    return int(round(min(100, v + breadth + level + change + min(trades, 3) / 3 * 10 + min(catalysts, 1) * 5)))


def reason(a: Dict, stress: Optional[Dict], trades: int, insider: Optional[float], catalysts: Iterable[str] = ()) -> str:
    """One line: the signals that are actually there, strongest first."""
    parts = []
    if insider is not None and abs(insider) >= 0.1:
        parts.append("Insider buying" if insider > 0 else "Insider selling")
    elif trades:
        parts.append(f"{trades} recent trade{'' if trades == 1 else 's'}")
    change = (stress or {}).get("change_24h")
    if change and abs(change) >= 5:
        parts.append(f"Tremor {'up' if change > 0 else 'down'} {abs(change)} in 24 h")
    parts.extend(list(catalysts)[:1])
    if a["last_hour"]:
        parts.append(f"{a['last_hour']} stor{'y' if a['last_hour'] == 1 else 'ies'} in 1h")
    else:
        parts.append(f"{a['day']} stories in 24h")
    return " + ".join(parts[:3])


def build(activity: Dict[str, Dict], stresses: Dict[str, Dict], trades: Dict[str, int], names: Dict[str, str],
          previous: Optional[List[Dict]] = None, catalysts: Optional[Dict[str, List[str]]] = None) -> List[Dict]:
    """The ranked rows. Companies under 3 stories in 24 h can't appear, so noise can't top the board."""
    catalysts = catalysts or {}
    rows = []
    for ticker, a in activity.items():
        if a["day"] < MIN_STORIES_24H:
            continue
        s = stresses.get(ticker)
        n = trades.get(ticker, 0)
        insider = ((s or {}).get("features") or {}).get("insider_flow")
        rows.append({"ticker": ticker, "name": names.get(ticker, ticker),
                     "score": move_score(a, s, n, len(catalysts.get(ticker, []))),
                     "stress": (s or {}).get("stress"), "reason": reason(a, s, n, insider, catalysts.get(ticker, [])),
                     "stories_24h": a["day"]})
    rows.sort(key=lambda r: (-r["score"], -r["stories_24h"], r["ticker"]))
    rows = rows[:SIZE]
    before = {r["ticker"]: r["rank"] for r in (previous or [])}
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        was = before.get(r["ticker"])
        r["change"] = (was - i) if was else 0
        r["new"] = bool(previous) and was is None
        r["jump"] = bool(was) and abs(was - i) >= 3
    return rows
