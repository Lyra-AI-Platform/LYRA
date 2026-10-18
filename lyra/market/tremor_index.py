"""The Tremor Index (TRX).

Each ticker gets its own reading, labelled TRX-<TICKER>:
  * p_boom  — probability the stock rises more than BOOM_THRESHOLD over the horizon
  * p_bust  — probability it falls more than BUST_THRESHOLD
  * score   — 0..100, 50 is neutral, above 50 leans boom, below leans bust
  * tremor  — chance of a big move either way (p_boom + p_bust)
  * causes  — the factors that pushed the reading, in plain English

Two small logistic models (boom and bust) turn the features into
probabilities. They start from hand-set priors and are re-fitted by the
learner every time a past prediction can be graded."""
import math
from typing import Dict, List, Optional

from lyra.market.config import INDEX_CODE, MAX_POSITION

# Every feature is scaled to roughly [-1, 1]; positive means bullish,
# except "uncertainty", which is non-directional (0..1).
FEATURES = [
    "momentum", "long_momentum", "trend", "short_term", "drawdown", "vol_vs_market", "market_fear", "fear_spike",
    "volume_surge", "news_sentiment", "news_buzz", "insider_flow", "insider_cluster", "fund_flow",
    "congress_flow", "quiet_accumulation", "peer_consensus", "uncertainty",
]

PRIOR_BOOM = {
    "bias": -0.85, "momentum": 0.45, "long_momentum": 0.2, "trend": 0.35, "short_term": 0.1, "drawdown": 0.15,
    "vol_vs_market": 0.1, "market_fear": 0.3, "fear_spike": 0.25, "volume_surge": 0.2,
    "news_sentiment": 0.5, "news_buzz": 0.2, "insider_flow": 0.8, "insider_cluster": 0.4,
    "fund_flow": 0.35, "congress_flow": 0.45, "quiet_accumulation": 0.5, "peer_consensus": 0.4,
    "uncertainty": 0.6,
}
PRIOR_BUST = {
    "bias": -1.1, "momentum": -0.35, "long_momentum": -0.2, "trend": -0.35, "short_term": -0.1, "drawdown": -0.3,
    "vol_vs_market": -0.3, "market_fear": -0.5, "fear_spike": -0.4, "volume_surge": -0.2,
    "news_sentiment": -0.6, "news_buzz": -0.2, "insider_flow": -0.6, "insider_cluster": -0.2,
    "fund_flow": -0.3, "congress_flow": -0.35, "quiet_accumulation": -0.4, "peer_consensus": -0.4,
    "uncertainty": 0.7,
}

EXPLAIN = {
    "momentum": ("strong 20-day price momentum", "falling 20-day price momentum"),
    "long_momentum": ("up strongly over the past year (excluding the last month)",
                      "down over the past year (excluding the last month)"),
    "trend": ("trading above its 50-day average", "trading below its 50-day average"),
    "short_term": ("rising over the past week", "sliding over the past week"),
    "drawdown": ("close to its 52-week high", "deep below its 52-week high"),
    "vol_vs_market": ("calmer than the overall market", "far more volatile than the market"),
    "market_fear": ("the market fear gauge (VIX) is low", "the market fear gauge (VIX) is elevated"),
    "fear_spike": ("market fear is easing", "market fear is spiking"),
    "volume_surge": ("unusual buying volume", "unusual selling volume"),
    "news_sentiment": ("the news is positive", "the news is negative"),
    "news_buzz": ("lots of upbeat coverage", "lots of downbeat coverage"),
    "insider_flow": ("company insiders are buying", "company insiders are selling"),
    "insider_cluster": ("3 or more insiders bought in the last 90 days", ""),
    "fund_flow": ("famous funds added to their stakes", "famous funds trimmed their stakes"),
    "congress_flow": ("politicians have been buying", "politicians have been selling"),
    "quiet_accumulation": ("insiders or politicians buying while news coverage is low",
                           "insiders or politicians selling while news coverage is low"),
    "peer_consensus": ("other systems in the network lean bullish", "other systems in the network lean bearish"),
    "uncertainty": ("high volatility — a big move is likely either way", ""),
}


def _t(x: float) -> float:
    return math.tanh(x)


def build_features(stats: Dict, vix: Dict, news: Dict, money: Dict, peers: Dict) -> Dict:
    """Turn raw inputs into {"values": {...}, "available": {...}}."""
    v: Dict[str, float] = {f: 0.0 for f in FEATURES}
    avail: Dict[str, bool] = {f: False for f in FEATURES}

    def put(name, value):
        v[name] = round(max(-1.0, min(1.0, value)), 4)
        avail[name] = True

    if stats:
        put("momentum", _t(stats["return_20d"] / 0.10))
        if stats.get("return_12m_ex_1m") is not None:
            put("long_momentum", _t(stats["return_12m_ex_1m"] / 0.40))
        put("trend", _t(stats["vs_sma50"] / 0.10))
        put("short_term", _t(stats["return_5d"] / 0.05))
        put("drawdown", -_t(stats["drawdown"] / 0.30))
        put("volume_surge", _t(stats["volume_z"] / 3) * (1 if stats["return_5d"] >= 0 else -1))
        put("uncertainty", _t(stats["realized_vol"] / 0.5))
        if vix.get("available"):
            put("vol_vs_market", -_t((stats["realized_vol"] - vix["level"] / 100) / 0.3))
    if vix.get("available"):
        put("market_fear", -_t((vix["level"] - 20) / 10))
        put("fear_spike", -_t(vix["change_5d"] / 0.25))
    if news.get("count_7d"):
        put("news_sentiment", _t(news["sentiment"] * 3))
        put("news_buzz", _t(news["count_7d"] / 20) * (1 if news["sentiment"] >= 0 else -1))
    if money:
        ins, con = money["insider_flow"], money["congress_flow"]
        if ins["trades"]:
            put("insider_flow", ins["score"])
            put("insider_cluster", 1.0 if ins["cluster_buying"] else 0.0)
        if money["funds"]:
            put("fund_flow", money["fund_score"])
        if con["trades"]:
            put("congress_flow", con["score"])
        if ins["trades"] or con["trades"]:
            # Smart money moving while the news is quiet is the closest public
            # proxy for trading on information others don't have yet.
            quiet = 1 - _t(news.get("count_7d", 0) / 5)
            put("quiet_accumulation", (ins["score"] + con["score"]) / 2 * quiet)
    if peers.get("peers"):
        put("peer_consensus", peers["edge"])
    return {"values": v, "available": avail}


class LogisticModel:
    def __init__(self, weights: Dict[str, float]):
        self.w = dict(weights)

    def z(self, x: Dict[str, float]) -> float:
        return self.w.get("bias", 0.0) + sum(self.w.get(k, 0.0) * x.get(k, 0.0) for k in FEATURES)

    def predict(self, x: Dict[str, float]) -> float:
        z = max(-30.0, min(30.0, self.z(x)))
        return 1 / (1 + math.exp(-z))

    def update(self, x: Dict[str, float], label: int, prior: Dict[str, float], lr: float = 0.05, l2: float = 0.01):
        """One SGD step on log-loss, regularised toward the prior so a few
        unlucky outcomes can't wipe out sensible defaults."""
        err = self.predict(x) - label
        for k in ["bias"] + FEATURES:
            grad = err * (1.0 if k == "bias" else x.get(k, 0.0)) + l2 * (self.w.get(k, 0.0) - prior.get(k, 0.0))
            self.w[k] = round(self.w.get(k, 0.0) - lr * grad, 6)
        return err


def explain(features: Dict[str, float], boom: LogisticModel, bust: LogisticModel,
            p_boom: float, p_bust: float, top: int = 5) -> List[Dict]:
    """Each feature's push on the boom-minus-bust edge, biggest first."""
    out = []
    for k in FEATURES:
        x = features.get(k, 0.0)
        if x == 0:
            continue
        push = p_boom * (1 - p_boom) * boom.w.get(k, 0) * x - p_bust * (1 - p_bust) * bust.w.get(k, 0) * x
        if k == "uncertainty":
            push = (p_boom * (1 - p_boom) * boom.w.get(k, 0) + p_bust * (1 - p_bust) * bust.w.get(k, 0)) * x
        bull, bear = EXPLAIN[k]
        text = bull if (x > 0) else bear
        if not text:
            continue
        out.append({"factor": k, "value": x, "impact": round(push, 4), "reason": text})
    out.sort(key=lambda c: abs(c["impact"]), reverse=True)
    return out[:top]


def decide(p_boom: float, p_bust: float, confidence: float, vix_level: Optional[float],
           price: Optional[float], portfolio_value: Optional[float] = None,
           shares_held: float = 0.0) -> Dict:
    """Turn probabilities into an action and a size an AI trader can execute."""
    edge = p_boom - p_bust
    fear_scale = 1.0 if not vix_level or vix_level <= 20 else max(0.4, 1 - (vix_level - 20) / 40)
    if edge >= 0.12 and confidence >= 0.3:
        action = "BUY"
        fraction = round(MAX_POSITION * min(1.0, edge / 0.4) * confidence * fear_scale, 4)
    elif edge <= -0.12 and confidence >= 0.3:
        action = "SELL"
        fraction = round(min(1.0, abs(edge) / 0.4 * confidence), 4)
    else:
        action, fraction = "HOLD", 0.0
    out = {"action": action, "edge": round(edge, 4), "confidence": round(confidence, 3)}
    if action == "BUY":
        out["portfolio_fraction"] = fraction
        if portfolio_value and price:
            out["amount"] = round(portfolio_value * fraction, 2)
            out["shares"] = math.floor(portfolio_value * fraction / price)
    elif action == "SELL":
        out["fraction_of_holding"] = fraction
        if shares_held:
            out["shares"] = math.floor(shares_held * fraction)
            if price:
                out["amount"] = round(out["shares"] * price, 2)
    return out


def label(ticker: str) -> str:
    return f"{INDEX_CODE}-{ticker.upper()}"
