"""Offline tests for the Tremor Index market expert. Network calls are faked."""
import asyncio
import json
import math
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone

os.environ.setdefault("LYRA_MARKET_DIR", tempfile.mkdtemp(prefix="lyra-market-test-"))

from lyra.market import expert, learner, news, sentiment, smart_money  # noqa: E402
from lyra.market import fetch as fetch_mod  # noqa: E402
from lyra.market.market_data import parse_yahoo_chart, price_stats  # noqa: E402
from lyra.market.store import get_store  # noqa: E402
from lyra.market.tremor_index import (PRIOR_BOOM, PRIOR_BUST, LogisticModel,  # noqa: E402
                                      build_features, decide)

TODAY = datetime.now(timezone.utc)
D = lambda days: (TODAY - timedelta(days=days)).strftime("%Y-%m-%d")  # noqa: E731

FORM4 = f"""<?xml version="1.0"?>
<ownershipDocument>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Huang Jen-Hsun</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector><isOfficer>1</isOfficer>
      <officerTitle>President and CEO</officerTitle></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>{D(5)}</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>10000</value></transactionShares>
        <transactionPricePerShare><value>120.5</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>{D(5)}</value></transactionDate>
      <transactionCoding><transactionCode>M</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>500</value></transactionShares>
        <transactionPricePerShare><value>0</value></transactionPricePerShare></transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""

INFOTABLE = """<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable><nameOfIssuer>NVIDIA CORPORATION</nameOfIssuer><cusip>67066G104</cusip><value>5000000</value>
    <shrsOrPrnAmt><sshPrnamt>{shares}</sshPrnamt></shrsOrPrnAmt></infoTable>
  <infoTable><nameOfIssuer>NVIDIA CORP</nameOfIssuer><cusip>67066G104</cusip><value>100</value>
    <shrsOrPrnAmt><sshPrnamt>99</sshPrnamt></shrsOrPrnAmt><putCall>Put</putCall></infoTable>
  <infoTable><nameOfIssuer>APPLE HOSPITALITY REIT INC</nameOfIssuer><cusip>03784Y200</cusip><value>1</value>
    <shrsOrPrnAmt><sshPrnamt>1</sshPrnamt></shrsOrPrnAmt></infoTable>
</informationTable>"""

RSS = f"""<?xml version="1.0"?><rss><channel>
<item><title>Nvidia beats estimates, raises guidance on record AI demand</title>
  <link>https://example.com/a1</link><pubDate>{TODAY.strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>
  <description>Strong growth.</description></item>
<item><title>Analyst warns of risk</title><link>https://example.com/a2</link>
  <pubDate>{TODAY.strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate><description></description></item>
</channel></rss>"""

ARTICLE_HTML = "<html><body><nav>menu</nav><article><p>" + "Nvidia reported record revenue and strong growth across segments. " * 5 + "</p></article></body></html>"


def chart(start: float, drift: float, n: int = 260):
    ts0 = time.time() - n * 86400
    closes = [start * (1 + drift) ** i * (1 + 0.01 * math.sin(i)) for i in range(n)]
    return json.dumps({"chart": {"result": [{"timestamp": [ts0 + i * 86400 for i in range(n)],
                                              "indicators": {"quote": [{"close": closes, "volume": [1e6 + 1e4 * (i % 7) for i in range(n)]}]}}]}})


def fake_routes(url: str):
    if "%5EVIX" in url:
        return chart(18, -0.001)
    if "finance/chart/NVDA" in url:
        return chart(80, 0.002)
    if url.endswith("company_tickers.json"):
        return json.dumps({"0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"}})
    if "CIK0001045810" in url:
        return json.dumps({"filings": {"recent": {"form": ["4"], "accessionNumber": ["0001-24-000001"],
                                                  "filingDate": [D(4)], "primaryDocument": ["xslF345X05/form4.xml"]}}})
    if url.endswith("/form4.xml"):
        return FORM4
    if "CIK0001067983" in url:
        return json.dumps({"filings": {"recent": {"form": ["13F-HR", "13F-HR"], "accessionNumber": ["A-1", "A-0"],
                                                  "filingDate": [D(40), D(130)]}}})
    if "/1067983/A1/index.json" in url or "/1067983/A0/index.json" in url:
        return json.dumps({"directory": {"item": [{"name": "primary_doc.xml"}, {"name": "infotable.xml"}]}})
    if "/1067983/A1/infotable.xml" in url:
        return INFOTABLE.format(shares=2000)
    if "/1067983/A0/infotable.xml" in url:
        return INFOTABLE.format(shares=1000)
    if "house-stock-watcher" in url:
        return json.dumps([{"ticker": "NVDA", "type": "purchase", "amount": "$15,001 - $50,000",
                            "representative": "Rep. Example", "transaction_date": D(10)}])
    if "rss" in url or "feeds" in url:
        return RSS
    if url.startswith("https://example.com/"):
        return ARTICLE_HTML
    return None


def install_fake_fetch(monkeypatch):
    async def fake(url, max_age=0, timeout=0):
        return fake_routes(url)
    for mod in (fetch_mod, news, smart_money, expert):
        if hasattr(mod, "fetch_text"):
            monkeypatch.setattr(mod, "fetch_text", fake)
    import lyra.market.market_data as md
    import lyra.market.peers as pr
    monkeypatch.setattr(md, "fetch_text", fake)
    monkeypatch.setattr(pr, "fetch_text", fake)


def test_sentiment_direction_and_negation():
    assert sentiment.score("Nvidia beats estimates and raises guidance") > 0
    assert sentiment.score("Shares plunge after fraud probe") < 0
    assert sentiment.score("company did not miss estimates") > 0
    assert sentiment.score("The meeting is on Tuesday") == 0


def test_parse_form4_keeps_only_open_market_trades():
    trades = smart_money.parse_form4(FORM4)
    assert len(trades) == 1
    t = trades[0]
    assert t["side"] == "buy" and t["value"] == 1205000.0
    assert "CEO" in t["role"] and smart_money.role_weight(t["role"]) == 1.0


def test_13f_matching_ignores_puts_and_lookalikes():
    rows = smart_money.parse_13f_infotable(INFOTABLE.format(shares=2000))
    assert smart_money._match_position(rows, "NVIDIA CORP")["shares"] == 2000
    assert smart_money._match_position(rows, "Apple Inc.")["shares"] == 0


def test_flow_score_weights_buys_over_sells():
    buy = smart_money.flow_score([{"person": "a", "role": "CEO", "side": "buy", "value": 1e6}])
    sell = smart_money.flow_score([{"person": "a", "role": "CEO", "side": "sell", "value": 1e6}])
    assert buy["score"] > 0 > sell["score"] and abs(buy["score"]) > abs(sell["score"])


def test_feed_and_article_extraction():
    items = news.parse_feed(RSS)
    assert len(items) == 2 and items[0]["url"] == "https://example.com/a1"
    text = news.extract_article_text(ARTICLE_HTML)
    assert "record revenue" in text and "menu" not in text


def test_decision_sizing_is_capped_and_scaled_by_fear():
    calm = decide(0.7, 0.1, 1.0, 15, 100, portfolio_value=10000)
    scared = decide(0.7, 0.1, 1.0, 40, 100, portfolio_value=10000)
    assert calm["action"] == "BUY" and calm["portfolio_fraction"] <= 0.05
    assert scared["portfolio_fraction"] < calm["portfolio_fraction"]
    assert calm["shares"] == math.floor(10000 * calm["portfolio_fraction"] / 100)
    sell = decide(0.1, 0.6, 0.8, 20, 100, shares_held=50)
    assert sell["action"] == "SELL" and 0 < sell["shares"] <= 50
    assert decide(0.3, 0.3, 1.0, 20, 100)["action"] == "HOLD"
    assert decide(0.9, 0.0, 0.1, 20, 100)["action"] == "HOLD"  # low confidence never trades


def test_learning_moves_weights_toward_outcomes():
    boom, bust = LogisticModel(PRIOR_BOOM), LogisticModel(PRIOR_BUST)
    x = {"insider_flow": 1.0}
    before = boom.predict(x)
    for _ in range(50):
        boom.update(x, 0, PRIOR_BOOM, lr=0.2)
    assert boom.predict(x) < before


def test_mistake_blames_misleading_factors():
    boom, bust = LogisticModel(PRIOR_BOOM), LogisticModel(PRIOR_BUST)
    pred = {"id": 1, "ticker": "XYZ", "action": "BUY", "p_boom": 0.7, "p_bust": 0.1,
            "features": {"insider_flow": 0.9, "news_sentiment": 0.5, "market_fear": -0.4}}
    res = learner.learn_from(pred, -0.12, boom, bust)
    assert res["outcome"] == "bust"
    blamed = [b["factor"] for b in res["mistake"]["blamed_factors"]]
    assert blamed[0] == "insider_flow" and "market_fear" not in blamed


def test_build_features_handles_missing_data():
    feats = build_features({}, {"available": False}, {"count_7d": 0}, {}, {})
    assert all(v == 0 for v in feats["values"].values())
    assert not any(feats["available"].values())


def test_end_to_end_analyze_offline(monkeypatch):
    install_fake_fetch(monkeypatch)
    r = asyncio.run(expert.analyze("nvda", portfolio_value=10000))
    assert r["label"] == "TRX-NVDA" and r["company"] == "NVIDIA CORP"
    assert 0 < r["p_boom"] < 1 and 0 < r["p_bust"] < 1 and 0 <= r["score"] <= 100
    assert r["smart_money"]["insiders"][0]["person"] == "Huang Jen-Hsun"
    assert r["smart_money"]["congress"][0]["person"] == "Rep. Example"
    assert r["smart_money"]["funds"][0]["change"] == 1.0  # 1000 -> 2000 shares
    assert r["features"]["insider_flow"] > 0 and r["features"]["news_sentiment"] > 0
    assert r["causes"] and r["prediction_id"]
    # Articles are stored with their full text for the in-app reader.
    stored = get_store().get_article(news.article_id("https://example.com/a1"))
    assert "record revenue" in stored["full_text"]
    assert "TRX-NVDA" in expert.ai_brief(r)

    # Pretend the horizon has passed and the stock crashed: the learner should grade it.
    store = get_store()
    store._exec("UPDATE predictions SET created_at=?, price=? WHERE id=?",
                (time.time() - 40 * 86400, 10_000.0, r["prediction_id"]))
    result = asyncio.run(learner.evaluate_due())
    assert result["graded"] >= 1
    hist = store.history("NVDA")
    assert hist[0]["outcome"] == "bust"
    assert store.load_weights("boom") is not None


# ── Risk guard ──────────────────────────────────────────────────────────────

from lyra.market import risk_guard  # noqa: E402
from lyra.market import store as store_mod  # noqa: E402

NOW = time.time()
CLEAN = {"equity": 10000, "invested": 0, "peak_equity": 10000, "day_start_equity": 10000, "daily_pnl": 0.0,
         "drawdown": 0.0, "trades_today": 0, "loss_streak": 0, "last_loss_ts": None, "last_trade_ts": {}}
BUY = decide(0.7, 0.1, 1.0, 15, 100, portfolio_value=10000)
CTX = {"ticker": "XYZ", "price": 100, "last_ts": NOW - 3600, "realized_vol": 0.3, "p_boom": 0.7,
       "p_bust": 0.1, "equity": 10000}


def guarded(decision=BUY, ctx=None, **state):
    return risk_guard.review(decision, {**CTX, **(ctx or {})}, {**CLEAN, **state}, now=NOW)


def blocked_by(d):
    return [c["check"] for c in d["risk"]["checks"] if c["status"] == "block"]


def test_guard_approves_clean_buy_and_attaches_stops():
    d = guarded()
    assert d["action"] == "BUY" and d["risk"]["approved"]
    assert d["stop_loss"] < 100 < d["take_profit"]
    assert (100 - d["stop_loss"]) * 2 == pytest_approx(d["take_profit"] - 100)
    assert d["portfolio_fraction"] <= BUY["portfolio_fraction"]


def pytest_approx(x):
    import pytest
    return pytest.approx(x, rel=1e-3)


def test_guard_blocks_stale_data_but_allows_exits():
    assert blocked_by(guarded(ctx={"last_ts": NOW - 10 * 86400})) == ["fresh_data"]
    sell = decide(0.1, 0.6, 0.8, 20, 100, shares_held=50)
    out = guarded(sell, ctx={"last_ts": NOW - 10 * 86400}, drawdown=0.5, daily_pnl=-0.2)
    assert out["action"] == "SELL"  # getting out is never blocked


def test_guard_daily_loss_drawdown_and_streak():
    assert "daily_loss_limit" in blocked_by(guarded(daily_pnl=-0.03))
    assert "drawdown_breaker" in blocked_by(guarded(drawdown=0.12))
    halved = guarded(drawdown=0.06, ctx={"realized_vol": 0.1})
    assert halved["action"] == "BUY" and halved["portfolio_fraction"] == pytest_approx(BUY["portfolio_fraction"] / 2)
    assert "loss_streak_cooldown" in blocked_by(guarded(loss_streak=3, last_loss_ts=NOW - 3600))
    assert guarded(loss_streak=3, last_loss_ts=NOW - 30 * 3600)["action"] == "BUY"


def test_guard_overtrading_costs_and_exposure():
    assert "overtrading" in blocked_by(guarded(trades_today=10))
    assert "overtrading" in blocked_by(guarded(last_trade_ts={"XYZ": NOW - 300}))
    weak = decide(0.30, 0.17, 1.0, 15, 100, portfolio_value=10000)
    assert weak["action"] == "BUY" and "cost_hurdle" in blocked_by(guarded(weak, ctx={"p_boom": 0.30, "p_bust": 0.27}))
    assert "exposure" in blocked_by(guarded(ctx={"invested": 6000}))
    capped = guarded(ctx={"invested": 5900})
    assert capped["portfolio_fraction"] == pytest_approx(0.01)


def test_guard_sizes_from_stop_on_volatile_stocks():
    calm = guarded(ctx={"realized_vol": 0.2})
    wild = guarded(ctx={"realized_vol": 3.0})  # meme-stock volatility: stop is ~38% away
    assert wild["portfolio_fraction"] < calm["portfolio_fraction"]
    # If the stop is hit, the loss is at most RISK_PER_TRADE of equity.
    loss = wild["shares"] * (100 - wild["stop_loss"])
    assert loss <= 10000 * 0.01 + 1e-6


def test_account_state_tracks_pnl_and_losing_streak(monkeypatch, tmp_path):
    monkeypatch.setattr(store_mod, "_store", store_mod.MarketStore(tmp_path / "acct.db"))
    s = store_mod.get_store()
    s.record_equity("alice", 10000, ts=NOW - 2 * 86400)
    s.record_equity("alice", 11000, ts=NOW - 86400 - 60)
    s.record_equity("alice", 10500, ts=NOW)
    s.record_equity("bob", 999999, ts=NOW)
    for i, (buy, sell) in enumerate([(100, 90), (50, 45), (20, 19)]):
        s.record_fill("alice", "ABC", "buy", 10, buy, ts=NOW - 600 + i * 10)
        s.record_fill("alice", "ABC", "sell", 10, sell, ts=NOW - 595 + i * 10)
    st = risk_guard.account_state("alice", NOW)
    assert st["peak_equity"] == 11000 and st["drawdown"] == pytest_approx(1 - 10500 / 11000)
    assert st["daily_pnl"] == pytest_approx(10500 / 11000 - 1)
    assert st["loss_streak"] == 3 and st["trades_today"] >= 1
    assert s.fills("alice", ticker="ABC")[1]["realized_pnl"] == -100.0
    # Another user's account is completely separate.
    bob = risk_guard.account_state("bob", NOW)
    assert bob["equity"] == 999999 and bob["loss_streak"] == 0 and bob["trades_today"] == 0
