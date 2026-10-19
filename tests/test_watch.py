"""Offline tests for Lyra Watch. Network calls are faked."""
import asyncio
import os
import tempfile

os.environ.setdefault("LYRA_MARKET_DIR", tempfile.mkdtemp(prefix="lyra-watch-test-"))

from lyra.watch import analysis, service, sources  # noqa: E402

PTR_TEXT = """Name: Hon. Nancy Pelosi
ID Owner Asset Transaction
Type
Date Notification
Date
Amount Cap.
Gains >
$200?
SP Intel Corporation - Common Stock
(INTC) [OP]
P 05/29/2026 05/29/2026 $1,000,001 -
$5,000,000
F\x00 S\x00: New
D\x00: Purchased 200 call options with a strike price of $50.
SP REOF XXX, LLC [AB] P 09/08/2026 09/08/2026 $500,001 -
$1,000,000
F S: New
D: Investment in LLC which is acquiring an office property.
SP Apple Inc. (AAPL) [ST] S (partial) 12/24/2025 12/24/2025 $5,000,001 -
$25,000,000
* For the complete list of asset type abbreviations, please visit https://fd.house.gov/
"""

INDEX_XML = """<FinancialDisclosure>
<Member><Prefix>Hon.</Prefix><Last>Pelosi</Last><First>Nancy</First><FilingType>P</FilingType>
<StateDst>CA11</StateDst><Year>2026</Year><FilingDate>6/23/2026</FilingDate><DocID>20034836</DocID></Member>
<Member><Last>Aaron</Last><First>Richard</First><FilingType>W</FilingType><StateDst>MI04</StateDst>
<Year>2026</Year><FilingDate>4/15/2026</FilingDate><DocID>8068</DocID></Member>
</FinancialDisclosure>"""


def test_parse_ptr_text_reads_stocks_options_and_private_holdings():
    rows = sources.parse_ptr_text(PTR_TEXT)
    assert [r["ticker"] for r in rows] == ["INTC", "", "AAPL"]
    intel, llc, apple = rows
    assert intel["company"] == "Intel Corporation" and intel["options"] and intel["side"] == "buy"
    assert intel["amount_range"] == "$1,000,001 - $5,000,000" and intel["value"] == 1000001
    assert intel["description"].startswith("Purchased 200 call options")
    assert llc["company"] == "REOF XXX, LLC" and llc["asset_type"] == "AB" and llc["date"] == "2026-09-08"
    assert apple["company"] == "Apple Inc." and apple["side"] == "sell" and apple["partial"]


def test_parse_house_index_keeps_only_ptrs():
    rows = sources.parse_house_index(INDEX_XML)
    assert rows == [{"last": "Pelosi", "first": "Nancy", "state": "CA11", "date": "6/23/2026",
                     "doc": "20034836", "year": "2026"}]


def test_position_changes_classifies_new_add_trim_exit():
    latest = [{"issuer": "APPLE INC", "cusip": "A", "value": 300.0, "shares": 3, "put_call": ""},
              {"issuer": "NEWMONT CORP", "cusip": "N", "value": 100.0, "shares": 1, "put_call": ""},
              {"issuer": "TRIMBLE INC", "cusip": "T", "value": 10.0, "shares": 1, "put_call": ""}]
    prior = [{"issuer": "APPLE INC", "cusip": "A", "value": 200.0, "shares": 2, "put_call": ""},
             {"issuer": "TRIMBLE INC", "cusip": "T", "value": 50.0, "shares": 5, "put_call": ""},
             {"issuer": "GONZAGA CO", "cusip": "G", "value": 70.0, "shares": 7, "put_call": ""}]
    actions = {c["company"]: c["action"] for c in sources.position_changes(latest, prior)}
    assert actions == {"Apple": "add", "Newmont": "new", "Trimble": "trim", "Gonzaga": "exit"}


def test_clean_company():
    assert sources.clean_company("LENNAR CORP /NEW/") == "Lennar"
    assert sources.clean_company("Bloom Energy Corporation") == "Bloom Energy Corporation"


def test_annotate_finds_companies_moves_and_topics():
    item = {"title": "Musk's SpaceX agrees deal to buy stake in Nvidia supplier as $TSLA slides",
            "summary": "The acquisition is subject to tariffs review."}
    a = analysis.annotate(item, {"TSLA"})
    tickers = {c["ticker"] for c in a["companies"]}
    assert {"SPCX", "NVDA", "TSLA"} <= tickers
    kinds = {m["kind"] for m in a["moves"]}
    assert {"deal", "policy"} <= kinds
    assert "Trade & tariffs" in a["topics"]


def test_cashtags_must_be_real_tickers():
    assert analysis.companies_in("Buy $NOPEX now", {"AAPL"}) == []


def test_ambiguous_words_are_not_companies():
    assert analysis.companies_in("Trump's new target is Shell-shocked Visa holders") == []


def test_traded_groups_buys_and_sells():
    rows = analysis.traded([
        {"ticker": "BE", "company": "Bloom", "side": "buy", "value": 100.0, "date": "2026-07-01"},
        {"ticker": "BE", "company": "Bloom", "side": "sell", "value": 50.0, "date": "2026-08-01"},
        {"company": "Apple", "action": "trim", "value_change": -500.0, "date": "2026-06-01"}])
    assert rows[0]["name"] == "Apple" and rows[0]["sells"] == 1 and rows[0]["value"] == 500.0
    assert rows[1] == {"name": "Bloom", "ticker": "BE", "buys": 1, "sells": 1, "value": 150.0, "last": "2026-08-01"}


def test_stance_requires_a_source():
    assert service._stance({"affiliation": {"label": "Labour Party"}})["basis"] == "none"
    s = service._stance({"affiliation": {"label": "Labour Party", "source": "https://example.org"}})
    assert s == {"label": "Labour Party", "source": "https://example.org", "basis": "documented"}


def test_build_profile_merges_sources(monkeypatch):
    async def fake_statements(person):
        return ([{"title": "Pelosi backs deal with Apple", "summary": "", "url": "https://x", "source": "X",
                  "published": 1.79e9, "own_words": False}], {"status": "ok", "provider": "news"})

    async def fake_house(last, state):
        return ([{"company": "Apple Inc.", "ticker": "AAPL", "side": "buy", "value": 1000.0,
                  "amount_range": "$1,001 - $15,000", "date": "2026-07-01", "url": "https://ptr",
                  "kind": "congress", "source": "House PTR"}], {"status": "ok", "provider": "house"})
    async def no_wiki(person):
        return {"status": "none"}
    monkeypatch.setattr(sources, "statements", fake_statements)
    monkeypatch.setattr(sources, "house_trades", fake_house)
    monkeypatch.setattr(sources, "wiki_person", no_wiki)
    person = {"slug": "p", "name": "P", "category": "politician", "country": "US", "role": "Rep",
              "house": {"last": "P", "state": "CA11"}}
    p = asyncio.run(service.build_profile(person))
    assert p["stance"]["basis"] == "none"
    assert p["summary"]["traded"][0]["ticker"] == "AAPL"
    assert {m["type"] for m in p["moves"]} == {"trade", "statement"}
    assert any(m["title"].startswith("Bought Apple Inc.") for m in p["moves"])
