"""The Market Expert: pulls everything together into a Tremor Index reading
for a ticker and a buy/sell/hold recommendation an AI agent can act on."""
import asyncio
import logging
import time
from typing import Dict, List, Optional

from lyra.market import backtest, learner, news, peers, risk_guard, smart_money
from lyra.market.config import (BOOM_THRESHOLD, BUST_THRESHOLD, EXPERIMENTAL_UNTIL_GRADED, HORIZON_DAYS,
                                INDEX_NAME, PERSONAL_SIZING)
from lyra.market.market_data import get_history, get_vix, history_status, price_stats
from lyra.market.store import get_store
from lyra.market.tremor_index import build_features, decide, explain, label

logger = logging.getLogger(__name__)

DISCLAIMER = ("General market information, not financial advice and not a recommendation to buy or "
              "sell. Probabilities come from an experimental model that has not been validated against "
              "historical data. It can and will be wrong. Prices are delayed daily closes.")
# A reading missing any of these is marked partial instead of being presented as complete.
CORE_SOURCES = ("price", "news", "insiders")
# Fields that size a trade to one person's portfolio (personal advice; see config.PERSONAL_SIZING).
SIZING_FIELDS = ("portfolio_fraction", "fraction_of_holding", "amount", "shares", "stop_loss",
                 "take_profit", "stop_distance")


def _confidence(avail: Dict[str, bool], peer_info: Dict, graded: int) -> float:
    groups = [
        (0.35, ["momentum", "trend"]),
        (0.15, ["market_fear"]),
        (0.25, ["news_sentiment"]),
        (0.25, ["insider_flow", "fund_flow", "congress_flow"]),
    ]
    coverage = sum(w for w, keys in groups if any(avail.get(k) for k in keys))
    maturity = 0.6 + 0.4 * min(1.0, graded / 50)
    return max(0.0, coverage * maturity * (1 - peer_info.get("disagreement", 0.0)))


def _day_start(ts: float) -> float:
    return ts - ts % 86400


async def analyze(ticker: str, portfolio_value: Optional[float] = None, shares_held: float = 0.0,
                  save: bool = True, owner: str = "local") -> Dict:
    ticker = ticker.upper().strip()
    if not PERSONAL_SIZING:
        portfolio_value, shares_held = None, 0.0
    company = await smart_money.lookup_company(ticker)
    company_name = company["name"] if company else ""
    bars, vix, news_report, money, peer_info = await asyncio.gather(
        get_history(ticker, "1y"),
        get_vix(),
        news.collect_news_report(ticker, company_name),
        smart_money.gather(ticker, company),
        peers.consult(ticker),
    )
    articles = news_report["articles"]
    stats = price_stats(bars)
    news_info = news.news_features(articles)
    feats = build_features(stats, vix, news_info, money, peer_info)
    boom, bust = learner.load_models()
    x = feats["values"]
    p_boom, p_bust = boom.predict(x), bust.predict(x)
    # Keep the two probabilities coherent: boom and bust can't add up past 1.
    if p_boom + p_bust > 0.98:
        s = (p_boom + p_bust) / 0.98
        p_boom, p_bust = p_boom / s, p_bust / s
    stats_db = get_store().prediction_stats()
    confidence = _confidence(feats["available"], peer_info, stats_db["evaluated"])
    price = stats.get("price")
    model_decision = decide(p_boom, p_bust, confidence, vix.get("level"), price, portfolio_value, shares_held)
    decision = risk_guard.review(model_decision, {
        "ticker": ticker, "price": price, "last_ts": stats.get("last_ts"),
        "realized_vol": stats.get("realized_vol"), "p_boom": p_boom, "p_bust": p_bust,
        "equity": portfolio_value, "shares_held": shares_held}, owner=owner)
    if not PERSONAL_SIZING:
        for k in SIZING_FIELDS:
            decision.pop(k, None)

    sources = {
        "price": history_status(bars),
        "vix": vix.get("source") or {"status": "ok" if vix.get("available") else "failed"},
        "news": {"status": news_report["status"], "provider": "RSS (Yahoo Finance, Google News)",
                 "feeds": news_report["feeds"], "articles_counted": len(articles),
                 "off_topic_dropped": news_report["off_topic_dropped"]},
        **money["sources"],
    }
    failed_core = [k for k in CORE_SOURCES if sources[k]["status"] in ("failed", "stale")]
    bt = backtest.load_result()
    proven = bool(bt.get("proven"))
    experimental = stats_db["evaluated"] < EXPERIMENTAL_UNTIL_GRADED

    reading = {
        "index": INDEX_NAME,
        "label": label(ticker),
        "ticker": ticker,
        "company": company_name,
        "created_at": time.time(),
        "price": round(price, 4) if price else None,
        "price_as_of": sources["price"].get("as_of"),
        "price_note": "daily close, delayed" if price else "price unavailable",
        "sources": sources,
        "partial": bool(failed_core),
        "failed_sources": failed_core,
        "experimental": experimental,
        "model_status": (f"Experimental: {stats_db['evaluated']} of {EXPERIMENTAL_UNTIL_GRADED} readings "
                         "graded so far. Treat the percentages as unproven." if experimental else
                         f"{stats_db['evaluated']} readings graded."),
        "track_record": {"graded": stats_db["evaluated"], "correct": stats_db.get("correct", 0)},
        # Until a backtest shows skill, readers see a lean and the causes, not exact percentages.
        "show_probabilities": proven,
        "backtest": {"verdict": bt.get("verdict"), "period": bt.get("period"),
                     "url": "/tremor/#backtest"} if bt else None,
        "horizon_days": HORIZON_DAYS,
        "p_boom": round(p_boom, 4),
        "p_bust": round(p_bust, 4),
        "score": round(50 + 50 * (p_boom - p_bust), 1),
        "tremor": round(p_boom + p_bust, 4),
        "definition": f"boom = +{BOOM_THRESHOLD:.0%} or more, bust = -{BUST_THRESHOLD:.0%} or more within {HORIZON_DAYS} days",
        "causes": explain(x, boom, bust, p_boom, p_bust),
        "decision": decision,
        "features": x,
        "market": {k: v for k, v in vix.items() if k != "history"},
        "price_stats": {k: round(v, 4) for k, v in stats.items() if v is not None},
        "news": {**news_info, "scoring": "word-list sentiment (lyra/market/sentiment.py) on headline and "
                 "summary; only articles naming the ticker or company are counted",
                 "headlines": [
            {"id": a["id"], "title": a["title"], "source": a["source"], "url": a["url"],
             "sentiment": a["sentiment"], "published": a["published"]} for a in articles[:25]]},
        "smart_money": {
            "insider_flow": money["insider_flow"], "congress_flow": money["congress_flow"],
            "fund_score": round(money["fund_score"], 4),
            "insiders": sorted(money["insiders"], key=lambda t: t.get("date", ""), reverse=True)[:15],
            "congress": sorted(money["congress"], key=lambda t: t.get("date", ""), reverse=True)[:15],
            "funds": money["funds"],
        },
        "peers": peer_info,
        "disclaimer": DISCLAIMER,
    }
    # One graded reading per ticker per day, so a popular ticker can't dominate the track record.
    if save and price and not failed_core and not get_store().prediction_saved_since(
            ticker, _day_start(reading["created_at"])):
        reading["prediction_id"] = get_store().save_prediction({
            "ticker": ticker, "created_at": reading["created_at"], "price": price,
            "horizon_days": HORIZON_DAYS, "features": x, "p_boom": p_boom, "p_bust": p_bust,
            "action": model_decision["action"]})  # grade the model's call, not the guard's veto
    return reading


async def scan(tickers: List[str], portfolio_value: Optional[float] = None, owner: str = "local") -> List[Dict]:
    """Analyse several tickers (sequentially, to be polite to data sources), best edge first."""
    out = []
    for t in tickers:
        try:
            out.append(await analyze(t, portfolio_value, owner=owner))
        except Exception as e:
            logger.warning(f"Tremor scan failed for {t}: {e}")
    out.sort(key=lambda r: r["decision"]["edge"], reverse=True)
    return out


def ai_brief(reading: Dict) -> str:
    """Compact text an LLM can drop into its context before deciding on a trade."""
    d = reading["decision"]
    lines = [
        f"{reading['label']} ({reading['company'] or reading['ticker']}) — {INDEX_NAME} reading",
        f"Price {reading['price']} ({reading['price_note']}, {reading.get('price_as_of') or 'n/a'}) | score {reading['score']}/100 | P(boom) {reading['p_boom']:.0%} | "
        f"P(bust) {reading['p_bust']:.0%} | {reading['definition']}",
        f"Market: VIX {reading['market'].get('level', 'n/a')} ({reading['market'].get('regime', 'unknown')})",
        f"Suggested action: {d['action']} (edge {d['edge']:+.2f}, confidence {d['confidence']:.0%})"
        + (f", {d['portfolio_fraction']:.2%} of portfolio" if "portfolio_fraction" in d else "")
        + (f", sell {d['fraction_of_holding']:.0%} of holding" if "fraction_of_holding" in d else "")
        + (f", ~{d['shares']} shares" if d.get("shares") else ""),
    ]
    if d.get("stop_loss"):
        lines.append(f"Stop-loss {d['stop_loss']} | take-profit {d['take_profit']} — place both with the order.")
    vetoes = [c["detail"] for c in d.get("risk", {}).get("checks", []) if c["status"] == "block"]
    if vetoes:
        lines.append(f"Risk guard overrode {d['original_action']} -> HOLD: " + "; ".join(vetoes))
    if reading.get("partial"):
        lines.append("PARTIAL READING — sources failed: " + ", ".join(reading["failed_sources"]))
    if reading.get("experimental"):
        lines.append(reading["model_status"])
    lines.append("Why:")
    lines += [f"  - {c['reason']} ({c['impact']:+.3f})" for c in reading["causes"]]
    lines.append(reading["disclaimer"])
    return "\n".join(lines)


class LearningLoop:
    """Background task: grade matured predictions once every few hours."""

    def __init__(self, interval_hours: float = 6):
        self.interval = interval_hours * 3600
        self._task: Optional[asyncio.Task] = None

    async def _run(self):
        while True:
            try:
                await learner.evaluate_due()
            except Exception as e:
                logger.warning(f"Tremor learner error: {e}")
            await asyncio.sleep(self.interval)

    def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.get_event_loop().create_task(self._run())

    def stop(self):
        if self._task:
            self._task.cancel()


learning_loop = LearningLoop()
