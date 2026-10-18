"""Learning from mistakes.

Every reading is saved. Once its horizon has passed, the learner looks up
what the price actually did, labels the outcome (boom / bust / flat),
nudges both models toward the truth, and records confident wrong calls in
the mistake log together with the factors that misled it. Factors that keep
misleading lose weight; ones that keep being right gain it."""
import logging
from typing import Dict

from lyra.market.config import BOOM_THRESHOLD, BUST_THRESHOLD
from lyra.market.market_data import get_history, price_on_or_after
from lyra.market.store import get_store
from lyra.market.tremor_index import FEATURES, PRIOR_BOOM, PRIOR_BUST, LogisticModel

logger = logging.getLogger(__name__)


def load_models():
    store = get_store()
    return (LogisticModel(store.load_weights("boom") or PRIOR_BOOM),
            LogisticModel(store.load_weights("bust") or PRIOR_BUST))


def outcome_of(ret: float) -> str:
    return "boom" if ret >= BOOM_THRESHOLD else "bust" if ret <= -BUST_THRESHOLD else "flat"


def _expected(action: str) -> str:
    return {"BUY": "boom", "SELL": "bust"}.get(action, "flat")


def learn_from(prediction: Dict, ret: float, boom: LogisticModel, bust: LogisticModel) -> Dict:
    """Grade one prediction and update the models in place."""
    x = prediction["features"]
    outcome = outcome_of(ret)
    boom.update(x, int(outcome == "boom"), PRIOR_BOOM)
    bust.update(x, int(outcome == "bust"), PRIOR_BUST)
    result = {"outcome": outcome, "return": ret, "mistake": None}
    action = prediction["action"]
    missed_move = action == "HOLD" and outcome != "flat" and max(prediction["p_boom"], prediction["p_bust"]) < 0.3
    if (action != "HOLD" and _expected(action) != outcome) or missed_move:
        # Blame the factors that pointed the wrong way. If nothing happened
        # after a BUY/SELL, blame the strongest factors behind that call.
        if outcome == "flat":
            wrong_sign = 1 if action == "BUY" else -1
        else:
            wrong_sign = -1 if outcome == "boom" else 1
        blamed = sorted(
            ({"factor": k, "value": x.get(k, 0.0)} for k in FEATURES
             if k != "uncertainty" and x.get(k, 0.0) * wrong_sign > 0),
            key=lambda b: abs(b["value"]), reverse=True)[:3]
        result["mistake"] = {"prediction_id": prediction["id"], "ticker": prediction["ticker"],
                             "predicted": action, "actual": outcome,
                             "outcome_return": round(ret, 4), "blamed_factors": blamed}
    return result


async def evaluate_due() -> Dict:
    """Grade every prediction whose horizon has passed and retrain."""
    store = get_store()
    due = store.due_predictions()
    if not due:
        return {"graded": 0, "mistakes": 0}
    boom, bust = load_models()
    histories: Dict[str, list] = {}
    graded = mistakes = 0
    for p in due:
        if p["ticker"] not in histories:
            histories[p["ticker"]] = await get_history(p["ticker"], "2y")
        later = price_on_or_after(histories[p["ticker"]], p["created_at"] + p["horizon_days"] * 86400)
        if later is None or not p["price"]:
            continue
        ret = later / p["price"] - 1
        result = learn_from(p, ret, boom, bust)
        store.mark_evaluated(p["id"], round(ret, 4), result["outcome"])
        if result["mistake"]:
            store.log_mistake(result["mistake"])
            mistakes += 1
        graded += 1
    store.save_weights("boom", boom.w)
    store.save_weights("bust", bust.w)
    logger.info(f"Tremor Index learner graded {graded} predictions, {mistakes} mistakes")
    return {"graded": graded, "mistakes": mistakes}
