"""Market impact: what a listed company's stock actually did on the days a person was in the
news about it, measured against that stock's ordinary days. And "said & traded": a person's
disclosed trades next to the days they were in the news about the same company.

Every refresh adds the day's (person, ticker, date) mentions to a saved history, so the record
grows past the 30-day news window and gets more reliable every day.

Honest limits, shown with every number: news and price moves come together in both directions
(a stock move is itself news), so this measures what happened on those days, not what caused it.
"""
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from statistics import pstdev
from typing import Dict, List, Optional

from lyra.market import market_data
from lyra.watch.config import WATCH_DIR

logger = logging.getLogger(__name__)

HISTORY_FILE = WATCH_DIR / "impact_history.json"
KEEP_DAYS = 400
BIG_Z = 2.0          # a "big move": two of the stock's usual daily swings
SIGMA_DAYS = 60      # the usual swing is measured over the previous 60 trading days
MIN_EVENTS = 5       # fewer news days than this and no verdict is given
MAX_TICKERS = 80     # price histories fetched per refresh
TRADE_WINDOW = 30    # days either side of a trade


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def load_history() -> Dict:
    try:
        return json.loads(HISTORY_FILE.read_text())
    except (OSError, ValueError):
        return {"people": {}, "names": {}}


def remember(records: List[Dict], history: Optional[Dict] = None, now: Optional[float] = None) -> Dict:
    """Adds each record's ticker_days to the saved history and drops days older than KEEP_DAYS.
    history["people"][id][ticker] = [dates]; history["names"][ticker] = company name."""
    history = history or load_history()
    cutoff = _day((now or time.time()) - KEEP_DAYS * 86400)
    for rec in records:
        mine = history["people"].setdefault(rec["id"], {})
        for ticker, info in (rec.get("ticker_days") or {}).items():
            mine[ticker] = sorted(set(mine.get(ticker, [])) | set(info["dates"]))
            history["names"][ticker] = info.get("name") or history["names"].get(ticker, ticker)
    for pid, tickers in list(history["people"].items()):
        for t in list(tickers):
            tickers[t] = [d for d in tickers[t] if d >= cutoff]
            if not tickers[t]:
                del tickers[t]
        if not tickers:
            del history["people"][pid]
    return history


def save_history(history: Dict):
    try:
        tmp = HISTORY_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(history))
        tmp.replace(HISTORY_FILE)
    except OSError as e:
        logger.warning(f"Impact history not saved: {e}")


# ── Price moves ────────────────────────────────────────────────────────────

def daily_moves(bars: List[Dict]) -> Dict[str, Dict]:
    """date -> {"move": close-to-close return, "z": move / usual swing} for each trading day
    with SIGMA_DAYS of history before it."""
    out = {}
    closes = [b["close"] for b in bars]
    rets = [closes[i] / closes[i - 1] - 1 if closes[i - 1] > 0 else 0.0 for i in range(1, len(closes))]
    for i in range(SIGMA_DAYS, len(rets)):
        sigma = pstdev(rets[i - SIGMA_DAYS:i])
        if sigma > 0:
            out[_day(bars[i + 1]["ts"])] = {"move": rets[i], "z": rets[i] / sigma}
    return out


def trading_day(moves: Dict[str, Dict], day: str, days: List[str]) -> Optional[str]:
    """The news day itself if the market traded, otherwise the next session (weekend news
    shows up on Monday). None if that session hasn't closed yet."""
    for d in days:
        if d >= day:
            return d if (datetime.fromisoformat(d) - datetime.fromisoformat(day)).days <= 3 else None
    return None


def baseline(moves: Dict[str, Dict]) -> float:
    """Share of all trading days that were big moves for this stock."""
    if not moves:
        return 0.0
    return sum(abs(m["z"]) >= BIG_Z for m in moves.values()) / len(moves)


def person_impact(tickers: Dict[str, List[str]], prices: Dict[str, Dict[str, Dict]], names: Dict[str, str]) -> Dict:
    """One person's record across the companies they were in the news about."""
    events, by_ticker = [], []
    for ticker, dates in tickers.items():
        moves = prices.get(ticker)
        if not moves:
            continue
        days = sorted(moves)
        hit = sorted({d for d in (trading_day(moves, x, days) for x in dates) if d})
        if not hit:
            continue
        rows = [{"date": d, "ticker": ticker, "move": round(moves[d]["move"], 4), "z": round(moves[d]["z"], 2)} for d in hit]
        events += [(r, baseline(moves)) for r in rows]
        big = sum(abs(r["z"]) >= BIG_Z for r in rows)
        by_ticker.append({"ticker": ticker, "name": names.get(ticker, ticker), "days": len(rows), "big_moves": big,
                          "avg_move": round(sum(r["move"] for r in rows) / len(rows), 4),
                          "avg_abs_z": round(sum(abs(r["z"]) for r in rows) / len(rows), 2),
                          "usual_big_share": round(baseline(moves), 3)})
    if not events:
        return {"days": 0, "verdict": "no data", "by_ticker": [], "biggest": []}
    n = len(events)
    big = sum(abs(r["z"]) >= BIG_Z for r, _ in events)
    usual = sum(b for _, b in events) / n
    share = big / n
    lift = share / usual if usual > 0 else 0.0
    verdict = ("not enough days yet" if n < MIN_EVENTS else
               "strong" if lift >= 2 and big >= 2 else "some" if lift >= 1.3 and big >= 1 else "none seen")
    by_ticker.sort(key=lambda t: t["days"], reverse=True)
    return {"days": n, "big_moves": big, "big_share": round(share, 3), "usual_big_share": round(usual, 3),
            "lift": round(lift, 2), "avg_abs_z": round(sum(abs(r["z"]) for r, _ in events) / n, 2),
            "verdict": verdict, "first_day": min(r["date"] for r, _ in events),
            "by_ticker": by_ticker[:6],
            "biggest": sorted((r for r, _ in events), key=lambda r: abs(r["z"]), reverse=True)[:5]}


async def price_moves(tickers: List[str]) -> Dict[str, Dict[str, Dict]]:
    out = {}
    for t in tickers[:MAX_TICKERS]:
        try:
            bars = await market_data.get_history(t, "2y")
        except Exception:  # noqa: BLE001
            bars = []
        if len(bars) > SIGMA_DAYS + 2:
            out[t] = daily_moves(bars)
    return out


async def measure(records: List[Dict]) -> Dict:
    """Updates the saved history with these records, fetches prices for the tickers that matter
    most, and sets rec["market_impact"] (and rec["said_and_traded"] where trades are given).
    Returns {"by_ticker": {ticker: [person ids by impact]}, "prices": n}."""
    history = remember(records)
    save_history(history)
    weight: Dict[str, int] = {}
    for tickers in history["people"].values():
        for t, dates in tickers.items():
            weight[t] = weight.get(t, 0) + len(dates)
    prices = await price_moves(sorted(weight, key=weight.get, reverse=True))
    for rec in records:
        mine = history["people"].get(rec["id"], {})
        rec["market_impact"] = person_impact(mine, prices, history["names"])
        if rec.get("trades"):
            rec["said_and_traded"] = said_and_traded(rec["trades"], mine)
    return {"prices": len(prices)}


# ── Said & traded ──────────────────────────────────────────────────────────

def said_and_traded(trades: List[Dict], days_by_ticker: Dict[str, List[str]]) -> List[Dict]:
    """Each disclosed trade in a listed company, with the days the person was in the news about
    that company in the TRADE_WINDOW days before and after it. Facts side by side, no judgement."""
    out: Dict[tuple, Dict] = {}
    for t in trades:
        ticker, date = (t.get("ticker") or "").upper(), t.get("date") or ""
        if not ticker or not date or t.get("side") == "filed":
            continue
        try:
            d = datetime.fromisoformat(date[:10])
        except ValueError:
            continue
        lo, hi = (d - timedelta(days=TRADE_WINDOW)).strftime("%Y-%m-%d"), (d + timedelta(days=TRADE_WINDOW)).strftime("%Y-%m-%d")
        news = days_by_ticker.get(ticker, [])
        before = [x for x in news if lo <= x < date[:10]]
        after = [x for x in news if date[:10] <= x <= hi]
        side = t.get("side") or t.get("action") or ""
        # One SEC filing often lists the same day's sale in many lines; they're one row here.
        row = out.setdefault((date[:10], ticker, side, t.get("kind", "")), {
            "date": date[:10], "ticker": ticker, "company": t.get("company") or ticker, "side": side,
            "kind": t.get("kind", ""), "trades": 0, "value": 0.0, "amount": t.get("amount_range") or "",
            "url": t.get("url", ""), "news_days_before": before, "news_days_after": after})
        row["trades"] += 1
        row["value"] += float(t.get("value") or 0)
    out = list(out.values())
    for row in out:
        if row["value"] and (row["trades"] > 1 or not row["amount"]):
            row["amount"] = f"${row['value']:,.0f}" + (f" in {row['trades']} trades" if row["trades"] > 1 else "")
    out.sort(key=lambda r: (len(r["news_days_before"]) + len(r["news_days_after"]), r["date"]), reverse=True)
    return out[:20]


def leaderboard(people: List[Dict], limit: int = 50) -> List[Dict]:
    """People with a verdict, highest lift first."""
    rows = [p for p in people if (p.get("market_impact") or {}).get("days", 0) >= MIN_EVENTS]
    rows.sort(key=lambda p: (p["market_impact"]["lift"], p["market_impact"]["days"]), reverse=True)
    return [{"id": p["id"], "name": p["name"], "job": p.get("job", ""),
             "popularity": p.get("popularity"), **{k: p["market_impact"][k] for k in
             ("days", "big_moves", "big_share", "usual_big_share", "lift", "avg_abs_z", "verdict", "by_ticker", "biggest")}}
            for p in rows[:limit]]
