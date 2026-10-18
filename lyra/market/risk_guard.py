"""Risk guard: the layer between a signal and an order.

The usual way an AI day trader dies isn't a bad prediction — it's having no
enforced risk discipline around its predictions:
  * positions sized without a stop, so one gap down takes a huge bite
  * trading on through a losing streak, doubling down to win it back
  * no daily loss limit or drawdown circuit breaker, so a bad day becomes a blown account
  * churning: small "edges" that the spread, fees and slippage eat whole
  * acting on stale or missing data as if it were live
  * stacking positions until the whole account rides on one market move

Every BUY/SELL passes through review() before it reaches the trader. The guard
can only make a decision smaller or turn it into HOLD; it never makes it bigger,
and it never blocks a SELL that reduces risk (getting out is always allowed)."""
import math
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from lyra.market.config import (BOOM_THRESHOLD, BUST_THRESHOLD, COOLDOWN_HOURS, DAILY_LOSS_LIMIT,
                                LOSS_STREAK_LIMIT, MAX_DATA_AGE_DAYS, MAX_DRAWDOWN, MAX_GROSS_EXPOSURE,
                                MAX_TRADES_PER_DAY, MIN_REENTRY_MINUTES, RISK_PER_TRADE, ROUND_TRIP_COST)
from lyra.market.store import get_store


def _day_start(now: float) -> float:
    d = datetime.fromtimestamp(now, timezone.utc)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()


def account_state(owner: str = "local", now: Optional[float] = None) -> Dict:
    """Where one owner's account stands, from the equity snapshots and fills they reported."""
    now = now or time.time()
    store = get_store()
    rows = store.equity_rows(owner)
    today = _day_start(now)
    state = {"equity": None, "invested": None, "peak_equity": None, "day_start_equity": None,
             "daily_pnl": 0.0, "drawdown": 0.0, "trades_today": 0, "loss_streak": 0,
             "last_loss_ts": None, "last_trade_ts": {}}
    if rows:
        latest = rows[-1]
        before_today = [r for r in rows if r["ts"] < today]
        start = (before_today[-1] if before_today else next(r for r in rows if r["ts"] >= today))["equity"]
        peak = max(r["equity"] for r in rows)
        state.update({
            "equity": latest["equity"], "invested": latest["invested"], "peak_equity": peak,
            "day_start_equity": start,
            "daily_pnl": latest["equity"] / start - 1 if start else 0.0,
            "drawdown": 1 - latest["equity"] / peak if peak else 0.0,
        })
    fills = store.fills(owner)
    state["trades_today"] = sum(1 for f in fills if f["ts"] >= today)
    for f in fills:
        state["last_trade_ts"][f["ticker"]] = f["ts"]
    for f in reversed([f for f in fills if f["realized_pnl"] is not None]):
        if f["realized_pnl"] >= 0:
            break
        state["loss_streak"] += 1
        state["last_loss_ts"] = state["last_loss_ts"] or f["ts"]
    return state


def stop_levels(price: float, realized_vol: float) -> Dict:
    """Volatility-based stop: 2x the typical daily move (at least 1%), with a 2:1 target."""
    daily_vol = (realized_vol or 0.3) / math.sqrt(252)
    dist = max(0.01, 2 * daily_vol)
    return {"stop_distance": round(dist, 4), "stop_loss": round(price * (1 - dist), 4),
            "take_profit": round(price * (1 + 2 * dist), 4)}


def review(decision: Dict, ctx: Dict, state: Optional[Dict] = None, now: Optional[float] = None,
           owner: str = "local") -> Dict:
    """Return a copy of `decision` that respects every risk limit, with a record of each check.

    ctx: price, last_ts (time of the latest price bar), realized_vol, p_boom, p_bust,
         equity (optional), shares_held."""
    now = now or time.time()
    state = state or account_state(owner, now)
    out = dict(decision)
    checks: List[Dict] = []
    action = decision["action"]
    price = ctx.get("price")
    equity = ctx.get("equity") or state.get("equity")

    def check(name, status, detail):
        checks.append({"check": name, "status": status, "detail": detail})

    def block(name, detail):
        check(name, "block", detail)
        out["action"] = "HOLD"

    if action == "HOLD":
        out["risk"] = {"approved": True, "checks": [], "account": _public(state)}
        return out

    # 1. Never act on data that isn't current.
    age_days = (now - ctx["last_ts"]) / 86400 if ctx.get("last_ts") else None
    if not price or age_days is None:
        if action == "BUY":
            block("fresh_data", "no current price — refusing to buy blind")
        else:
            check("fresh_data", "pass", "no current price, but exits are always allowed")
    elif age_days > MAX_DATA_AGE_DAYS:
        if action == "BUY":
            block("fresh_data", f"latest price is {age_days:.1f} days old")
        else:
            check("fresh_data", "pass", f"price is {age_days:.1f} days old, exits still allowed")
    else:
        check("fresh_data", "pass", f"price is {age_days * 24:.1f}h old")

    if action == "SELL":
        out["risk"] = {"approved": True, "checks": checks, "account": _public(state)}
        return out

    # From here on it's a BUY.
    # 2. Is the edge worth paying the spread and fees for?
    expected = ctx.get("p_boom", 0) * BOOM_THRESHOLD - ctx.get("p_bust", 0) * BUST_THRESHOLD
    if out["action"] == "BUY" and expected < 2 * ROUND_TRIP_COST:
        block("cost_hurdle", f"expected move {expected:.2%} doesn't clear 2x trading costs ({2 * ROUND_TRIP_COST:.2%})")
    elif out["action"] == "BUY":
        check("cost_hurdle", "pass", f"expected move {expected:.2%} vs costs {ROUND_TRIP_COST:.2%}")

    # 3. Daily loss limit.
    if out["action"] == "BUY" and state["daily_pnl"] <= -DAILY_LOSS_LIMIT:
        block("daily_loss_limit", f"down {-state['daily_pnl']:.2%} today (limit {DAILY_LOSS_LIMIT:.0%}) — no new buys until tomorrow")

    # 4. Drawdown circuit breaker; past halfway, sizes are halved.
    size_scale = 1.0
    if out["action"] == "BUY":
        if state["drawdown"] >= MAX_DRAWDOWN:
            block("drawdown_breaker", f"{state['drawdown']:.1%} below peak equity (limit {MAX_DRAWDOWN:.0%}) — buying halted")
        elif state["drawdown"] >= MAX_DRAWDOWN / 2:
            size_scale = 0.5
            check("drawdown_breaker", "adjust", f"{state['drawdown']:.1%} below peak — position size halved")

    # 5. Losing streak: cool off instead of revenge trading.
    if out["action"] == "BUY" and state["loss_streak"] >= LOSS_STREAK_LIMIT and state["last_loss_ts"]:
        hours_since = (now - state["last_loss_ts"]) / 3600
        if hours_since < COOLDOWN_HOURS:
            block("loss_streak_cooldown", f"{state['loss_streak']} losing trades in a row — cooling off for "
                                          f"{COOLDOWN_HOURS - hours_since:.1f} more hours")

    # 6. Overtrading.
    if out["action"] == "BUY" and state["trades_today"] >= MAX_TRADES_PER_DAY:
        block("overtrading", f"{state['trades_today']} trades today (limit {MAX_TRADES_PER_DAY})")
    last = state["last_trade_ts"].get(ctx.get("ticker", ""))
    if out["action"] == "BUY" and last and (now - last) / 60 < MIN_REENTRY_MINUTES:
        block("overtrading", f"traded {ctx.get('ticker')} {(now - last) / 60:.0f} min ago — no flip-flopping "
                             f"within {MIN_REENTRY_MINUTES:.0f} min")

    # 7. Size from the stop, and respect total exposure.
    if out["action"] == "BUY" and price:
        levels = stop_levels(price, ctx.get("realized_vol"))
        out.update({"stop_loss": levels["stop_loss"], "take_profit": levels["take_profit"]})
        fraction = out.get("portfolio_fraction", 0.0) * size_scale
        stop_cap = RISK_PER_TRADE / levels["stop_distance"]
        if stop_cap < fraction:
            check("stop_sizing", "adjust", f"cut to {stop_cap:.2%} of equity so hitting the stop "
                                           f"({levels['stop_distance']:.1%} away) loses at most {RISK_PER_TRADE:.0%}")
            fraction = stop_cap
        else:
            check("stop_sizing", "pass", f"stop {levels['stop_distance']:.1%} below entry risks "
                                         f"{fraction * levels['stop_distance']:.2%} of equity")
        invested = ctx.get("invested") if ctx.get("invested") is not None else state.get("invested")
        if equity and invested is not None:
            room = max(0.0, MAX_GROSS_EXPOSURE - invested / equity)
            if room <= 0:
                block("exposure", f"already {invested / equity:.0%} invested (limit {MAX_GROSS_EXPOSURE:.0%})")
            elif room < fraction:
                check("exposure", "adjust", f"only {room:.2%} of room left under the {MAX_GROSS_EXPOSURE:.0%} exposure cap")
                fraction = room
        if out["action"] == "BUY":
            out["portfolio_fraction"] = round(fraction, 4)
            if equity:
                out["amount"] = round(equity * fraction, 2)
                out["shares"] = math.floor(equity * fraction / price)
                if out["shares"] < 1:
                    block("min_size", "after risk limits the position rounds to zero shares")

    if out["action"] != "BUY":
        for k in ("portfolio_fraction", "amount", "shares", "stop_loss", "take_profit"):
            out.pop(k, None)
        out["original_action"] = action
    out["risk"] = {"approved": out["action"] == action, "checks": checks, "account": _public(state)}
    return out


def _public(state: Dict) -> Dict:
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in state.items() if k != "last_trade_ts"}
