"""Backtest of the Tremor Index on historical prices, with no look-ahead.

Replays daily data for a universe of large US stocks. On each sampled date it
builds the reading from data available on that date only (price history and
the VIX up to that close), predicts with the model's hand-set prior weights,
and grades it against the close 30 calendar days later, exactly as the live
learner does.

Only the price and VIX inputs can be replayed: there is no free point-in-time
archive of the news, insider, fund and politician data, so those inputs are
absent here. The result therefore tests the price/VIX half of the model, not
the whole live reading. The universe is today's large caps (survivorship bias:
companies that collapsed and left the index are missing).

Run: python -m lyra.market.backtest [--years 5] [--step 5]
Writes data/market/backtest.json, served at /api/market/public/backtest.
"""
import argparse
import asyncio
import json
import math
import time
from typing import Dict, List

from lyra.market.config import BOOM_THRESHOLD, BUST_THRESHOLD, DATA_DIR, HORIZON_DAYS
from lyra.market.learner import outcome_of
from lyra.market.market_data import get_history, price_on_or_after, price_stats
from lyra.market.store import get_store
from lyra.market.tremor_index import FEATURES, PRIOR_BOOM, PRIOR_BUST, LogisticModel, build_features, decide

RESULT_FILE = DATA_DIR / "backtest.json"

# Roughly the S&P 100 as of 2026.
UNIVERSE = [
    "AAPL", "ABBV", "ABT", "ACN", "ADBE", "AIG", "AMD", "AMGN", "AMT", "AMZN", "AVGO", "AXP", "BA", "BAC",
    "BK", "BKNG", "BLK", "BMY", "BRK-B", "C", "CAT", "CHTR", "CL", "CMCSA", "COF", "COP", "COST", "CRM",
    "CSCO", "CVS", "CVX", "DE", "DHR", "DIS", "DUK", "EMR", "F", "FDX", "GD", "GE", "GILD", "GM", "GOOGL",
    "GS", "HD", "HON", "IBM", "INTC", "INTU", "ISRG", "JNJ", "JPM", "KO", "LIN", "LLY", "LMT", "LOW", "MA",
    "MCD", "MDLZ", "MDT", "MET", "META", "MMM", "MO", "MRK", "MS", "MSFT", "NEE", "NFLX", "NKE", "NOW",
    "NVDA", "ORCL", "PEP", "PFE", "PG", "PM", "PYPL", "QCOM", "RTX", "SBUX", "SCHW", "SO", "SPG", "T",
    "TGT", "TMO", "TMUS", "TSLA", "TXN", "UNH", "UNP", "UPS", "USB", "V", "VZ", "WFC", "WMT", "XOM",
]


def _vix_asof(vix_bars: List[Dict], ts: float) -> Dict:
    past = [b for b in vix_bars if b["ts"] <= ts][-130:]
    if len(past) < 21:
        return {"available": False}
    closes = [b["close"] for b in past]
    return {"available": True, "level": closes[-1], "change_5d": closes[-1] / closes[-6] - 1}


def _confidence(avail: Dict[str, bool]) -> float:
    # Same coverage rule as the live expert, with no graded history yet.
    groups = [(0.35, ["momentum", "trend"]), (0.15, ["market_fear"])]
    return sum(w for w, keys in groups if any(avail.get(k) for k in keys)) * 0.6


def readings_for(ticker: str, bars: List[Dict], vix_bars: List[Dict], step: int,
                 boom: LogisticModel = None, bust: LogisticModel = None) -> List[Dict]:
    boom = boom or LogisticModel(PRIOR_BOOM)
    bust = bust or LogisticModel(PRIOR_BUST)
    out = []
    horizon = HORIZON_DAYS * 86400
    for i in range(252, len(bars), step):
        now = bars[i]
        if now["ts"] + horizon > bars[-1]["ts"]:
            break
        stats = price_stats(bars[: i + 1])          # only data up to this close
        vix = _vix_asof(vix_bars, now["ts"])
        feats = build_features(stats, vix, {}, {}, {})
        x = feats["values"]
        p_boom, p_bust = boom.predict(x), bust.predict(x)
        if p_boom + p_bust > 0.98:
            s = (p_boom + p_bust) / 0.98
            p_boom, p_bust = p_boom / s, p_bust / s
        action = decide(p_boom, p_bust, _confidence(feats["available"]), vix.get("level"), stats["price"])["action"]
        later = price_on_or_after(bars, now["ts"] + horizon)
        if later is None:
            break
        ret = later / stats["price"] - 1
        out.append({"ticker": ticker, "ts": now["ts"], "p_boom": p_boom, "p_bust": p_bust,
                    "action": action, "ret": ret, "outcome": outcome_of(ret), "x": x,
                    "confidence": _confidence(feats["available"]), "vix": vix.get("level"), "price": stats["price"]})
    return out


# ── Fitting ──────────────────────────────────────────────────────────────────
#
# The live model starts from hand-set weights. Here they are re-fitted on the
# first part of the history and judged on the later part it never saw
# (walk-forward), so the out-of-sample numbers are an honest estimate.

def fit_logistic(rows: List[Dict], target: str, prior: Dict[str, float], l2: float = 2.0) -> Dict[str, float]:
    """L2-regularised logistic regression by gradient descent. Features that never vary in the
    data (news, filings: no history here) keep their prior weight instead of being fitted."""
    import numpy as np
    feats = [f for f in FEATURES if any(r["x"].get(f, 0.0) != 0.0 for r in rows)]
    X = np.array([[1.0] + [r["x"].get(f, 0.0) for f in feats] for r in rows])
    y = np.array([1.0 if r["outcome"] == target else 0.0 for r in rows])
    w = np.zeros(X.shape[1])
    w[0] = math.log(max(y.mean(), 1e-3) / max(1 - y.mean(), 1e-3))   # start at the base rate
    n = len(rows)
    for _ in range(3000):
        p = 1 / (1 + np.exp(-np.clip(X @ w, -30, 30)))
        grad = X.T @ (p - y) / n
        grad[1:] += l2 * w[1:] / n
        w -= 0.5 * grad
    fitted = dict(prior)
    fitted["bias"] = round(float(w[0]), 6)
    for f, v in zip(feats, w[1:]):
        fitted[f] = round(float(v), 6)
    return fitted


def rescore(rows: List[Dict], boom: LogisticModel, bust: LogisticModel) -> List[Dict]:
    out = []
    for r in rows:
        p_boom, p_bust = boom.predict(r["x"]), bust.predict(r["x"])
        if p_boom + p_bust > 0.98:
            s = (p_boom + p_bust) / 0.98
            p_boom, p_bust = p_boom / s, p_bust / s
        action = decide(p_boom, p_bust, r["confidence"], r["vix"], r["price"])["action"]
        out.append({**r, "p_boom": p_boom, "p_bust": p_bust, "action": action})
    return out


def walk_forward(rows: List[Dict], train_fraction: float = 0.6) -> Dict:
    """Fit on the earliest train_fraction of dates, test on the rest. Returns both fits' test scores."""
    ts = sorted(r["ts"] for r in rows)
    cutoff = ts[int(len(ts) * train_fraction)]
    train = [r for r in rows if r["ts"] < cutoff]
    test = [r for r in rows if r["ts"] >= cutoff + HORIZON_DAYS * 86400]   # gap so no train window overlaps the test
    w_boom = fit_logistic(train, "boom", PRIOR_BOOM)
    w_bust = fit_logistic(train, "bust", PRIOR_BUST)
    fitted_test = rescore(test, LogisticModel(w_boom), LogisticModel(w_bust))
    return {
        "cutoff": time.strftime("%Y-%m-%d", time.gmtime(cutoff)),
        "train_readings": len(train), "test_readings": len(test),
        "prior_on_test": summarise(test),
        "fitted_on_test": summarise(fitted_test),
        "weights": {"boom": w_boom, "bust": w_bust},
    }


def _brier(ps: List[float], ys: List[int]) -> float:
    return sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(ps)


def _calibration(ps: List[float], ys: List[int], bins: int = 10) -> List[Dict]:
    rows = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, p in enumerate(ps) if lo <= p < hi or (b == bins - 1 and p == 1.0)]
        if idx:
            rows.append({"bin": f"{lo:.0%}–{hi:.0%}", "predicted": round(sum(ps[i] for i in idx) / len(idx), 4),
                         "observed": round(sum(ys[i] for i in idx) / len(idx), 4), "count": len(idx)})
    return rows


def summarise(rows: List[Dict]) -> Dict:
    n = len(rows)
    y_boom = [int(r["outcome"] == "boom") for r in rows]
    y_bust = [int(r["outcome"] == "bust") for r in rows]
    base_boom, base_bust = sum(y_boom) / n, sum(y_bust) / n
    expected = {"BUY": "boom", "SELL": "bust", "HOLD": "flat"}
    hits = sum(expected[r["action"]] == r["outcome"] for r in rows)
    by_action = {}
    for a in ("BUY", "SELL", "HOLD"):
        sel = [r for r in rows if r["action"] == a]
        if sel:
            by_action[a] = {"count": len(sel), "hit_rate": round(sum(expected[a] == r["outcome"] for r in sel) / len(sel), 4),
                            "avg_30d_return": round(sum(r["ret"] for r in sel) / len(sel), 4)}
    # Baseline: the same mix of BUY/SELL/HOLD calls assigned at random (a weighted coin flip).
    mix = {a: v["count"] / n for a, v in by_action.items()}
    outcome_freq = {"boom": base_boom, "bust": base_bust, "flat": 1 - base_boom - base_bust}
    random_hit = sum(mix[a] * outcome_freq[expected[a]] for a in mix)
    flat_freq = outcome_freq["flat"]
    return {
        "readings": n,
        "base_rates": {k: round(v, 4) for k, v in outcome_freq.items()},
        "brier": {
            "boom": round(_brier([r["p_boom"] for r in rows], y_boom), 4),
            "boom_baseline": round(_brier([base_boom] * n, y_boom), 4),
            "bust": round(_brier([r["p_bust"] for r in rows], y_bust), 4),
            "bust_baseline": round(_brier([base_bust] * n, y_bust), 4),
        },
        "hit_rate": round(hits / n, 4),
        "hit_rate_random_same_mix": round(random_hit, 4),
        "hit_rate_always_hold": round(flat_freq, 4),
        "by_action": by_action,
        "avg_30d_return_all": round(sum(r["ret"] for r in rows) / n, 4),
        "calibration": {"boom": _calibration([r["p_boom"] for r in rows], y_boom),
                        "bust": _calibration([r["p_bust"] for r in rows], y_bust)},
    }


def skill(s: Dict) -> Dict:
    b = s["brier"]
    return {"boom": round(1 - b["boom"] / b["boom_baseline"], 4) if b["boom_baseline"] else 0.0,
            "bust": round(1 - b["bust"] / b["bust_baseline"], 4) if b["bust_baseline"] else 0.0}


def verdict(s: Dict) -> str:
    b = s["brier"]
    # A baseline Brier of 0 means the outcome never occurred in the sample; no skill can be shown.
    skill_boom = 1 - b["boom"] / b["boom_baseline"] if b["boom_baseline"] else 0.0
    skill_bust = 1 - b["bust"] / b["bust_baseline"] if b["bust_baseline"] else 0.0
    beats = s["hit_rate"] > s["hit_rate_random_same_mix"]
    if skill_boom > 0.02 and skill_bust > 0.02 and beats:
        return "The price/VIX model beats the simple baselines on this data."
    return ("The price/VIX model does not beat a simple base-rate forecast on data it was not trained on, so its "
            "percentages should be read as unproven leanings, not measured probabilities.")


async def run(years: int = 5, step: int = 5, tickers: List[str] = UNIVERSE) -> Dict:
    rng = f"{years}y"
    vix_bars = await get_history("^VIX", rng)
    rows, used, failed = [], [], []
    for t in tickers:
        bars = await get_history(t, rng)
        if len(bars) < 300:
            failed.append(t)
            continue
        used.append(t)
        rows += readings_for(t, bars, vix_bars, step)
        await asyncio.sleep(0.3)  # be polite to the data source
    if not rows:
        raise RuntimeError("no price data")
    s = summarise(rows)
    wf = walk_forward(rows)
    fitted = wf["fitted_on_test"]
    prior_test = wf["prior_on_test"]
    fitted_skill = skill(fitted)
    # Adopt the fitted weights when they do better than the hand-set ones on unseen data and are
    # no worse than the base rate. "Proven" is a higher bar: clear skill on both sides plus a hit
    # rate above the random baseline. Only a proven model gets its percentages shown.
    adopt = (fitted["brier"]["boom"] < prior_test["brier"]["boom"] and fitted["brier"]["bust"] < prior_test["brier"]["bust"]
             and fitted_skill["boom"] >= 0 and fitted_skill["bust"] >= 0)
    proven = (fitted_skill["boom"] > 0.02 and fitted_skill["bust"] > 0.02
              and fitted["hit_rate"] > fitted["hit_rate_random_same_mix"])
    if adopt:
        # The fitted weights become the live model's starting point; the learner keeps adjusting them.
        store = get_store()
        store.save_weights("boom", wf["weights"]["boom"])
        store.save_weights("bust", wf["weights"]["bust"])
    first, last = min(r["ts"] for r in rows), max(r["ts"] for r in rows)
    result = {
        "generated_at": time.time(),
        "period": {"from": time.strftime("%Y-%m-%d", time.gmtime(first)),
                   "to": time.strftime("%Y-%m-%d", time.gmtime(last))},
        "horizon_days": HORIZON_DAYS,
        "definition": f"boom = +{BOOM_THRESHOLD:.0%} or more, bust = -{BUST_THRESHOLD:.0%} or more, "
                      f"close to close over {HORIZON_DAYS} calendar days",
        "sampling": f"every {step} trading days per ticker",
        "tickers_used": used, "tickers_failed": failed,
        "inputs_tested": ["momentum", "trend", "short_term", "drawdown", "volume_surge", "uncertainty",
                          "vol_vs_market", "market_fear", "fear_spike"],
        "inputs_not_tested": ["news", "insider trades", "fund holdings", "politician trades", "peers"],
        "weights": "hand-set priors (the starting weights every live reading uses before learning)",
        "limitations": [
            "News, insider, fund and politician inputs have no point-in-time history here, so they are not tested.",
            "The universe is today's large caps, so stocks that failed or left the index are missing (survivorship bias).",
            "Readings overlap (30-day windows sampled every week), so they are not independent.",
            "Prices are Yahoo Finance daily closes; dividends are not included in returns.",
        ],
        "summary": s,
        "walk_forward": {k: v for k, v in wf.items() if k != "weights"},
        "fitted_weights": wf["weights"],
        "skill": {"prior_all": skill(s), "prior_test": skill(wf["prior_on_test"]), "fitted_test": fitted_skill},
        "fitted_adopted": adopt,
        "proven": proven,
    }
    if proven:
        result["verdict"] = ("Re-fitted price/VIX weights beat the base-rate baselines on data they were not trained on "
                             f"(Brier skill boom {fitted_skill['boom']:+.1%}, bust {fitted_skill['bust']:+.1%}; "
                             f"hit rate {fitted['hit_rate']:.1%} vs {fitted['hit_rate_random_same_mix']:.1%} random). "
                             "They are the live model's starting weights.")
    elif adopt:
        result["verdict"] = ("The hand-set weights did worse than a base-rate forecast. Weights re-fitted on the first "
                             f"part of the history do slightly better than base rates on the later part they never saw "
                             f"(Brier skill boom {fitted_skill['boom']:+.1%}, bust {fitted_skill['bust']:+.1%}; hit rate "
                             f"{fitted['hit_rate']:.1%} vs {fitted['hit_rate_random_same_mix']:.1%} random), so they are now "
                             "the live starting weights. The edge is small and unproven, so exact percentages stay hidden.")
    else:
        result["verdict"] = verdict(s)
    RESULT_FILE.write_text(json.dumps(result, indent=1))
    return result


def load_result() -> Dict:
    try:
        return json.loads(RESULT_FILE.read_text())
    except (OSError, ValueError):
        return {}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--step", type=int, default=5)
    a = ap.parse_args()
    r = asyncio.run(run(a.years, a.step))
    print(json.dumps({k: r[k] for k in ("period", "verdict")} | {"summary": {k: v for k, v in r["summary"].items()
                                                                             if k != "calibration"}}, indent=1))
    print(json.dumps({"skill": r["skill"], "fitted_adopted": r["fitted_adopted"],
                      "walk_forward": {k: v for k, v in r["walk_forward"].items() if k in ("cutoff", "train_readings", "test_readings")},
                      "fitted_test": {k: v for k, v in r["walk_forward"]["fitted_on_test"].items() if k != "calibration"}}, indent=1))
    print(f"{len(r['tickers_used'])} tickers, {len(r['tickers_failed'])} failed")
