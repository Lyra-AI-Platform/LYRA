"""
Lyra Market Expert API
Tremor Index readings, AI trade decisions, news headlines and the learning log.

Everything here is for signed-in users only and rate limited per account, so
the data can't be scraped anonymously or pulled out in bulk. Peer endpoints
(signal sharing with other Lyra nodes) need the LYRA_PEER_KEY shared secret
and are switched off when it isn't set.
"""
import hmac
import os
import time
from collections import defaultdict, deque
from typing import Deque, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel

from lyra.api.users_api import get_current_user
from lyra.db.models import User
from lyra.market import expert, learner, news, peers, risk_guard
from lyra.market.market_data import get_vix
from lyra.market.store import get_store

# Requests per account per hour. Analyses are expensive and are what a scraper
# would want, so they get the tightest limit.
LIMITS = {"analyze": int(os.environ.get("LYRA_MARKET_ANALYSES_PER_HOUR", 40)),
          "read": int(os.environ.get("LYRA_MARKET_READS_PER_HOUR", 400))}
_hits: Dict[str, Deque[float]] = defaultdict(deque)


def _limit(kind: str, key: str):
    now = time.time()
    q = _hits[f"{kind}:{key}"]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= LIMITS[kind]:
        raise HTTPException(429, f"Rate limit reached ({LIMITS[kind]} per hour). Try again later.",
                            headers={"Retry-After": str(int(3600 - (now - q[0])) + 1)})
    q.append(now)


def _private(response: Response):
    # Keep readings out of shared caches, Cloudflare's cache and search engines.
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"


def reader(response: Response, user: User = Depends(get_current_user)) -> User:
    _private(response)
    _limit("read", str(user.id))
    return user


def analyst(response: Response, user: User = Depends(get_current_user)) -> User:
    _private(response)
    _limit("analyze", str(user.id))
    return user


def peer(response: Response, x_lyra_peer_key: str = Header(default="")):
    expected = os.environ.get("LYRA_PEER_KEY", "")
    if not expected or not hmac.compare_digest(x_lyra_peer_key, expected):
        raise HTTPException(404, "Not found")
    _private(response)
    _limit("analyze", "peer:" + x_lyra_peer_key[:8])


def _owner(user: User) -> str:
    return f"user:{user.id}"


router = APIRouter(prefix="/api/market", tags=["market"])


class DecisionRequest(BaseModel):
    ticker: str
    portfolio_value: Optional[float] = None
    shares_held: float = 0.0


class AccountRequest(BaseModel):
    equity: float
    invested: Optional[float] = None


class FillRequest(BaseModel):
    ticker: str
    side: str
    shares: float
    price: float


class ScanRequest(BaseModel):
    tickers: List[str]
    portfolio_value: Optional[float] = None


@router.get("/vix")
async def vix(user: User = Depends(reader)):
    """Current CBOE VIX with context."""
    return await get_vix()


@router.get("/index/{ticker}")
async def tremor_reading(ticker: str, user: User = Depends(analyst)):
    """Full Tremor Index reading for one ticker (saved so it can be graded later)."""
    return await expert.analyze(ticker, owner=_owner(user))


@router.post("/decision")
async def decision(request: DecisionRequest, user: User = Depends(analyst)):
    """Buy/sell/hold plus size, for an AI agent, after the risk guard has reviewed it.
    Includes a text brief for LLM context."""
    if request.portfolio_value:
        get_store().record_equity(_owner(user), request.portfolio_value)
    reading = await expert.analyze(request.ticker, request.portfolio_value, request.shares_held,
                                   owner=_owner(user))
    return {"ticker": reading["ticker"], "label": reading["label"], "decision": reading["decision"],
            "p_boom": reading["p_boom"], "p_bust": reading["p_bust"], "score": reading["score"],
            "causes": reading["causes"], "brief": expert.ai_brief(reading),
            "prediction_id": reading.get("prediction_id")}


@router.post("/scan")
async def scan(request: ScanRequest, response: Response, user: User = Depends(get_current_user)):
    if len(request.tickers) > 10:
        raise HTTPException(400, "Scan at most 10 tickers at a time")
    _private(response)
    for _ in request.tickers:  # each ticker counts as one analysis
        _limit("analyze", str(user.id))
    readings = await expert.scan(request.tickers, request.portfolio_value, owner=_owner(user))
    return {"readings": [{k: r[k] for k in ("label", "ticker", "company", "price", "score", "p_boom",
                                            "p_bust", "tremor", "decision", "causes")} for r in readings]}


@router.get("/signal/{ticker}")
async def signal(ticker: str, _: None = Depends(peer)):
    """Lightweight signal for peer nodes in the network (not saved as a prediction)."""
    r = await expert.analyze(ticker, save=False)
    return {"ticker": r["ticker"], "p_boom": r["p_boom"], "p_bust": r["p_bust"], "score": r["score"],
            "ts": r["created_at"]}


@router.get("/signals.json")
async def signals_export(tickers: str, _: None = Depends(peer)):
    """Publishable signal file (commit it to a GitHub repo for other nodes). ?tickers=NVDA,AAPL"""
    readings = await expert.scan([t for t in tickers.split(",") if t.strip()][:10])
    return peers.export_signals(readings)


@router.get("/news")
async def news_list(ticker: str = "", q: str = "", limit: int = 50, refresh: bool = False,
                    user: User = Depends(reader)):
    """Every stored article, newest first. refresh=true pulls the latest feeds first."""
    if refresh and ticker:
        _limit("analyze", str(user.id))
        await news.collect_news(ticker)
    return {"articles": get_store().list_articles(ticker, q, limit=min(limit, 50))}


@router.get("/news/{article_id}")
async def news_article(article_id: str, user: User = Depends(reader)):
    """Headline, short summary and a link to the publisher. Full article text is never served."""
    a = get_store().get_article(article_id)
    if not a:
        raise HTTPException(404, "Article not found")
    return {k: a[k] for k in ("id", "ticker", "title", "source", "url", "published", "sentiment")} | {
        "summary": (a.get("summary") or "")[:news.SUMMARY_CHARS]}


@router.get("/history/{ticker}")
async def history(ticker: str, user: User = Depends(reader)):
    return {"predictions": get_store().history(ticker)}


@router.get("/learning")
async def learning_status(user: User = Depends(reader)):
    store = get_store()
    boom, bust = learner.load_models()
    return {"stats": store.prediction_stats(), "mistakes": store.mistakes(20),
            "weights": {"boom": boom.w, "bust": bust.w}}


@router.post("/learning/evaluate")
async def learning_evaluate(user: User = Depends(analyst)):
    """Grade every prediction whose horizon has passed and retrain now."""
    return await learner.evaluate_due()


@router.post("/account")
async def account_update(request: AccountRequest, user: User = Depends(reader)):
    """Report current equity (and amount invested) so the risk guard can track daily P&L and drawdown."""
    if request.equity <= 0:
        raise HTTPException(400, "equity must be positive")
    get_store().record_equity(_owner(user), request.equity, request.invested)
    state = risk_guard.account_state(_owner(user))
    state.pop("last_trade_ts", None)
    return state


@router.post("/fills")
async def fill(request: FillRequest, user: User = Depends(reader)):
    """Report an executed trade so the guard can count trades and losing streaks."""
    side = request.side.lower()
    if side not in ("buy", "sell") or request.shares <= 0 or request.price <= 0:
        raise HTTPException(400, "side must be buy/sell with positive shares and price")
    return get_store().record_fill(_owner(user), request.ticker, side, request.shares, request.price)


@router.get("/risk")
async def risk_status(user: User = Depends(reader)):
    """Account state as the risk guard sees it: daily P&L, drawdown, streaks, trade count."""
    state = risk_guard.account_state(_owner(user))
    state.pop("last_trade_ts", None)
    return state
