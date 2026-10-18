"""
Lyra Market Expert API
Tremor Index readings, AI trade decisions, the news reader and the learning log.
"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from lyra.market import expert, learner, news, peers
from lyra.market.market_data import get_vix
from lyra.market.store import get_store

router = APIRouter(prefix="/api/market", tags=["market"])


class DecisionRequest(BaseModel):
    ticker: str
    portfolio_value: Optional[float] = None
    shares_held: float = 0.0


class ScanRequest(BaseModel):
    tickers: List[str]
    portfolio_value: Optional[float] = None


@router.get("/vix")
async def vix():
    """Current CBOE VIX with context."""
    return await get_vix()


@router.get("/index/{ticker}")
async def tremor_reading(ticker: str):
    """Full Tremor Index reading for one ticker (saved so it can be graded later)."""
    return await expert.analyze(ticker)


@router.post("/decision")
async def decision(request: DecisionRequest):
    """Buy/sell/hold plus size, for an AI agent. Includes a text brief for LLM context."""
    reading = await expert.analyze(request.ticker, request.portfolio_value, request.shares_held)
    return {"ticker": reading["ticker"], "label": reading["label"], "decision": reading["decision"],
            "p_boom": reading["p_boom"], "p_bust": reading["p_bust"], "score": reading["score"],
            "causes": reading["causes"], "brief": expert.ai_brief(reading),
            "prediction_id": reading.get("prediction_id")}


@router.post("/scan")
async def scan(request: ScanRequest):
    if len(request.tickers) > 25:
        raise HTTPException(400, "Scan at most 25 tickers at a time")
    readings = await expert.scan(request.tickers, request.portfolio_value)
    return {"readings": [{k: r[k] for k in ("label", "ticker", "company", "price", "score", "p_boom",
                                            "p_bust", "tremor", "decision", "causes")} for r in readings]}


@router.get("/signal/{ticker}")
async def signal(ticker: str):
    """Lightweight signal for peer nodes in the network (not saved as a prediction)."""
    r = await expert.analyze(ticker, save=False, fetch_full_articles=False)
    return {"ticker": r["ticker"], "p_boom": r["p_boom"], "p_bust": r["p_bust"], "score": r["score"],
            "ts": r["created_at"]}


@router.get("/signals.json")
async def signals_export(tickers: str):
    """Publishable signal file (commit it to a GitHub repo for other nodes). ?tickers=NVDA,AAPL"""
    readings = await expert.scan([t for t in tickers.split(",") if t.strip()][:25])
    return peers.export_signals(readings)


@router.get("/news")
async def news_list(ticker: str = "", q: str = "", limit: int = 50, refresh: bool = False):
    """Every stored article, newest first. refresh=true pulls the latest feeds first."""
    if refresh and ticker:
        await news.collect_news(ticker)
    return {"articles": get_store().list_articles(ticker, q, limit=min(limit, 200))}


@router.get("/news/{article_id}")
async def news_article(article_id: str):
    """One article with its full text, so it can be read without leaving Lyra."""
    a = get_store().get_article(article_id)
    if not a:
        raise HTTPException(404, "Article not found")
    return a


@router.get("/history/{ticker}")
async def history(ticker: str):
    return {"predictions": get_store().history(ticker)}


@router.get("/learning")
async def learning_status():
    store = get_store()
    boom, bust = learner.load_models()
    return {"stats": store.prediction_stats(), "mistakes": store.mistakes(20),
            "weights": {"boom": boom.w, "bust": bust.w}}


@router.post("/learning/evaluate")
async def learning_evaluate():
    """Grade every prediction whose horizon has passed and retrain now."""
    return await learner.evaluate_due()
