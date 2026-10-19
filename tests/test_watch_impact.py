"""Offline tests for market impact and said & traded, on synthetic prices."""
import asyncio
import os
import tempfile
from datetime import datetime, timedelta, timezone

os.environ.setdefault("LYRA_MARKET_DIR", tempfile.mkdtemp(prefix="lyra-watch-test-"))

from lyra.watch import impact, service  # noqa: E402

START = datetime(2026, 1, 1, 21, tzinfo=timezone.utc)


def bars(days=120, jumps=None):
    """Weekday closes alternating ±1%, with given {date: return} jumps."""
    out, close, d, i = [], 100.0, START, 0
    while len(out) < days:
        if d.weekday() < 5:
            day = d.strftime("%Y-%m-%d")
            close *= 1 + (jumps or {}).get(day, 0.01 if i % 2 else -0.01)
            out.append({"ts": d.timestamp(), "close": close, "volume": 1})
            i += 1
        d += timedelta(days=1)
    return out


def trading_days(b):
    return [datetime.fromtimestamp(x["ts"], timezone.utc).strftime("%Y-%m-%d") for x in b]


def test_big_moves_on_news_days_give_a_strong_verdict():
    days = trading_days(bars())
    news = days[70:100:5]                       # six news days
    prices = impact.daily_moves(bars(jumps={d: 0.06 for d in news}))
    assert prices[news[0]]["z"] > impact.BIG_Z
    rec = impact.person_impact({"NVDA": news}, {"NVDA": prices}, {"NVDA": "Nvidia"})
    assert rec["days"] == 6 and rec["big_moves"] == 6 and rec["verdict"] == "strong"
    assert rec["lift"] > 2 and rec["by_ticker"][0]["name"] == "Nvidia"
    assert rec["biggest"][0]["ticker"] == "NVDA"


def test_quiet_news_days_and_too_few_days():
    days = trading_days(bars())
    prices = impact.daily_moves(bars(jumps={days[110]: 0.08}))
    quiet = impact.person_impact({"AAPL": days[70:100:5]}, {"AAPL": prices}, {})
    assert quiet["big_moves"] == 0 and quiet["verdict"] == "none seen"
    few = impact.person_impact({"AAPL": days[70:72]}, {"AAPL": prices}, {})
    assert few["verdict"] == "not enough days yet"
    assert impact.person_impact({"ZZZ": days[70:80]}, {}, {})["verdict"] == "no data"


def test_weekend_news_counts_on_monday_and_unclosed_days_are_skipped():
    b = bars()
    days = trading_days(b)
    prices = impact.daily_moves(b)
    sat = next(d for d in days[80:] if datetime.fromisoformat(d).weekday() == 0)  # a Monday
    saturday = (datetime.fromisoformat(sat) - timedelta(days=2)).strftime("%Y-%m-%d")
    assert impact.trading_day(prices, saturday, sorted(prices)) == sat
    assert impact.trading_day(prices, "2099-01-01", sorted(prices)) is None


def test_history_grows_and_prunes():
    now = datetime(2026, 10, 19, tzinfo=timezone.utc).timestamp()
    h = impact.remember([{"id": "a", "ticker_days": {"NVDA": {"name": "Nvidia", "dates": ["2026-10-01"]}}}],
                        {"people": {"a": {"NVDA": ["2025-01-01", "2026-09-01"]}}, "names": {}}, now=now)
    assert h["people"]["a"]["NVDA"] == ["2026-09-01", "2026-10-01"]  # 2025-01-01 is past KEEP_DAYS
    assert h["names"]["NVDA"] == "Nvidia"


def test_said_and_traded_lines_up_news_days_with_trades():
    rows = impact.said_and_traded(
        [{"ticker": "nvda", "date": "2026-06-15", "side": "buy", "kind": "congress", "amount_range": "$1,001 - $15,000"},
         {"ticker": "", "date": "2026-06-01", "side": "sell"},
         {"ticker": "AAPL", "date": "2026-06-10", "side": "filed"}],
        {"NVDA": ["2026-05-01", "2026-06-01", "2026-06-14", "2026-06-20", "2026-08-30"]})
    assert len(rows) == 1
    assert rows[0]["news_days_before"] == ["2026-06-01", "2026-06-14"]
    assert rows[0]["news_days_after"] == ["2026-06-20"]


def test_measure_and_impact_endpoint(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from lyra.api import watch_api
    from lyra.market import market_data

    impact.HISTORY_FILE.unlink(missing_ok=True)
    days = trading_days(bars())
    news = days[70:100:5]
    priced = bars(jumps={d: 0.06 for d in news})

    async def history(symbol, range_="1y"):
        return priced if symbol == "NVDA" else []
    monkeypatch.setattr(market_data, "get_history", history)
    recs = [{"id": "jensen-huang", "name": "Jensen Huang", "watched": True, "job": "CEO", "mentions": 9,
             "companies": [{"name": "Nvidia", "ticker": "NVDA"}], "tone": {"avg": 0, "label": "neutral"},
             "popularity": {"score": 80, "tier": "Household name"},
             "ticker_days": {"NVDA": {"name": "Nvidia", "dates": news}},
             "trades": [{"ticker": "NVDA", "date": news[2], "side": "sell", "kind": "insider"}]}]
    asyncio.run(impact.measure(recs))
    assert recs[0]["market_impact"]["verdict"] == "strong"
    assert recs[0]["said_and_traded"][0]["news_days_before"] == news[:2]
    service.save_people({"built_at": 1.0, "people": recs})

    app = FastAPI()
    app.include_router(watch_api.router)
    client = TestClient(app)
    body = client.get("/api/watch/impact").json()
    assert body["people"][0]["name"] == "Jensen Huang" and "not what caused it" in body["method"]
    assert client.get("/api/watch/impact?ticker=nvda").json()["people"][0]["this_stock"]["ticker"] == "NVDA"
    assert client.get("/api/watch/impact?ticker=AAPL").json()["people"] == []


def test_money_amounts_are_not_the_company_3m():
    from lyra.watch import analysis
    names = lambda t: [c["name"] for c in analysis.companies_in(t)]
    assert "3M" not in names("Ellison's $3M NIL bet on Michigan QB tanks")
    assert "3M" not in names("Jay-Z's Three Yankee Stadium Shows Gross $42.3M")
    assert "3M" in names("3M cuts its outlook as tariffs bite")


def test_said_and_traded_merges_one_days_filing_lines():
    rows = impact.said_and_traded([{"ticker": "META", "date": "2026-09-24", "side": "sell", "kind": "insider", "value": 1000.0}] * 3,
                                  {"META": ["2026-09-20"]})
    assert len(rows) == 1 and rows[0]["trades"] == 3 and rows[0]["amount"] == "$3,000 in 3 trades"
