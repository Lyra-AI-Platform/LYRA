"""Offline tests for the Lyra Watch people tracker. Headlines are real Google News
titles from October 2026, so these pin how the extractor reads actual media wording."""
import asyncio
import os
import tempfile

import pytest

os.environ.setdefault("LYRA_MARKET_DIR", tempfile.mkdtemp(prefix="lyra-watch-test-"))

from lyra.watch import people, service, sources  # noqa: E402

# (headline, every person it names) — Title Case, sentence case, possessives, hyphens,
# honorifics, names no list knows, and headlines that name nobody.
HEADLINES = [
    ("Home Office Deports Stanislav Carpiuc After Arson Attacks Targeting Sir Keir Starmer",
     ["Stanislav Carpiuc", "Keir Starmer"]),
    ("Why Wall Street Is Treating Elon Musk’s Flying Acrobat With Caution", ["Elon Musk"]),
    ("Taylor Swift Heroine Clara Bow’s Breakout Movie ‘It’ Leads Carlotta Films, Artcraft Pictures Deal",
     ["Taylor Swift", "Clara Bow"]),
    ("Nvidia CEO Jensen Huang Rejects Sam Altman's Advice to 'Accept' AI Cybersecurity Risks",
     ["Jensen Huang", "Sam Altman"]),
    ("Dakota Johnson Introduces Taylor Swift as Her 'Therapist' During SNL Monologue",
     ["Dakota Johnson", "Taylor Swift"]),
    ("Will Taylor Swift Pass The Beatles for the Most Hot 100 No. 1 Hits?", ["Taylor Swift"]),
    ("What Taylor Swift Can Teach You About Owning Your Business", ["Taylor Swift"]),
    ("Who is Sagal Abdi-Wali? Somali-born MP taking over Starmer's seat in UK's Camden", ["Sagal Abdi-Wali"]),
    ("Ex-Scottish Leader on Starmer’s Gaza Legacy | Aaron Bastani meets Humza Yousaf",
     ["Aaron Bastani", "Humza Yousaf"]),
    ("House Speaker Mike Johnson draws on faith as he fights to hold the Republican majority", ["Mike Johnson"]),
    ("Here's where Scott Wiener, Connie Chan stand in SF congressional race to succeed Nancy Pelosi",
     ["Scott Wiener", "Connie Chan", "Nancy Pelosi"]),
    ("Nvidia CEO Jensen Huang Just Reaffirmed His Jaw-Dropping Projection for 2030", ["Jensen Huang"]),
    ("Taylor Swift's New Instagram Bio Sparks Fan Theories About Upcoming Album Release", ["Taylor Swift"]),
    ("Labour Increasingly Confident Of Beating Zack Polanski In Crunch By-Election", ["Zack Polanski"]),
    ("He Journeyed Deep Into Elon Musk’s Brain. Spoiler: It Wasn’t Pretty.", ["Elon Musk"]),
    ("San Francisco Congressional Hopefuls Debate AI, Billionaires and, of Course, Housing", []),
    ("Tompkins DA says he won't be distracted by Jane Doe attorney's 'unfair' claims", []),
    ("Zelensky says Musk-owned satellite system still restricted in Ukraine", []),
    ("Elon Musk donates over $150 million to Senate GOP group, assisting Ken Paxton", ["Elon Musk", "Ken Paxton"]),
    ("CoreWeave Drops. Even Jensen Huang and Cathie Wood Can’t Buoy the Stock.", ["Jensen Huang", "Cathie Wood"]),
    ("Mohammed bin Salman meets Luiz Inácio Lula da Silva in Riyadh", ["Mohammed bin Salman",
                                                                      "Luiz Inácio Lula da Silva"]),
]


@pytest.mark.parametrize("text,expected", HEADLINES)
def test_names_in_real_headlines(text, expected):
    assert people.names_in(text) == expected


def test_names_are_stable_across_runs():
    first = [people.names_in(t) for t, _ in HEADLINES]
    assert all([people.names_in(t) for t, _ in HEADLINES] == first for _ in range(3))


def test_headline_drops_the_outlet():
    assert people.headline({"title": "Tim Bonner: Starmer’s legacy - That Eric Alper",
                            "source": "That Eric Alper"}) == "Tim Bonner: Starmer’s legacy"
    assert people.headline({"title": "Keir Starmer house firebomber deported - The Telegraph"}) == \
        "Keir Starmer house firebomber deported"


@pytest.mark.parametrize("text,name,job", [
    ("Nvidia CEO Jensen Huang defends CoreWeave as default risk rises", "Jensen Huang", "Nvidia CEO"),
    ("Why Nvidia CEO Jensen Huang Believes Suffering Is Part of Success", "Jensen Huang", "Nvidia CEO"),
    ("House Speaker Mike Johnson draws on faith", "Mike Johnson", "House Speaker"),
    ("Judge says Musk intimidated ex-FEMA CFO Mary Comans, clears her name", "Mary Comans", "FEMA CFO"),
    ("Who is Sagal Abdi-Wali, the Somali-born MP who won Starmer’s seat?", "Sagal Abdi-Wali", "Somali-born MP"),
    ("Olly Robbins wins payout over Mandelson scandal sacking", "Olly Robbins", ""),
])
def test_job_hint(text, name, job):
    assert people.job_hint(text, name) == job


def _item(title, feed, url, sentiment=0.0, companies=(), date="2026-10-18"):
    return {"title": title, "summary": "", "url": url, "date": date, "source": "X", "sentiment": sentiment,
            "companies": list(companies), "people": people.names_in(title), "feed": feed}


ROSTER = [{"slug": "keir-starmer", "name": "Keir Starmer", "role": "Former UK Prime Minister"},
          {"slug": "jay-z", "name": "Jay-Z (Shawn Carter)", "role": "Musician"}]


def test_build_index_resolves_surnames_and_filters_one_offs():
    media = [
        _item("Britain PM Andy Burnham drops Keir Starmer's jury trial policy", "Keir Starmer", "u1", -0.4),
        _item("Burnham sidelines Starmer’s AI data centre project", "Keir Starmer", "u2", -0.2,
              [{"name": "Palantir", "ticker": "PLTR"}]),
        _item("Burnham Finds His Plans to Focus on Britain Blown Up by Trump", "Keir Starmer", "u3", -0.3),
        _item("Olly Robbins wins payout over Mandelson scandal sacking", "Keir Starmer", "u4"),
        _item("Shawn Carter's Roc Nation signs a new act", "Jay-Z (Shawn Carter)", "u5", 0.5),
        _item("Britain PM Andy Burnham drops Keir Starmer's jury trial policy", "Keir Starmer", "u1"),  # duplicate url
    ]
    idx = people.build_index(media, ROSTER)
    burnham = idx["Andy Burnham"]
    assert burnham["mentions"] == 3 and not burnham["watched"]
    assert burnham["job"] == "Britain PM" and burnham["job_source"] == "headline"
    assert burnham["companies"][0]["ticker"] == "PLTR"
    assert burnham["tone"]["label"] == "negative"
    assert burnham["seen_with"] == ["Keir Starmer"]
    assert idx["Keir Starmer"]["watched"] and idx["Keir Starmer"]["mentions"] == 2
    assert idx["Keir Starmer"]["job"] == "Former UK Prime Minister"
    assert idx["Jay-Z"]["slug"] == "jay-z" and idx["Jay-Z"]["mentions"] == 1  # alias in parentheses
    assert "Olly Robbins" not in idx  # one headline isn't enough for someone off the watchlist


def test_popularity_scale_and_tiers():
    top = people.popularity(250_000, 100)
    assert top["score"] == 100 and top["tier"] == "Global name"
    mid = people.popularity(2_000, 10)
    assert 50 <= mid["score"] < 70 and mid["daily_views"] == 2000
    nobody = people.popularity(None, 3, "none")
    assert nobody["score"] <= 30 and nobody["tier"] == "Niche" and "no Wikipedia" in nobody["basis"]
    offline = people.popularity(None, 100, "unavailable")
    assert offline["score"] == 100 and "unreachable" in offline["basis"]
    assert people.popularity(10, 1)["score"] < people.popularity(1_000, 1)["score"] < people.popularity(100_000, 1)["score"]


def test_wiki_title_prefers_the_sourced_article():
    assert sources._wiki_title({"name": "Lula", "affiliation": {"source": "https://en.wikipedia.org/wiki/Lula_X"}}) == "Lula_X"
    assert sources._wiki_title({"name": "Jay-Z (Shawn Carter)"}) == "Jay-Z"
    assert sources._wiki_title({"name": "A B", "wiki": "C_D"}) == "C_D"


def test_build_people_rates_everyone(monkeypatch):
    roster = [{"slug": "keir-starmer", "name": "Keir Starmer", "role": "Former UK Prime Minister"}]
    media = [_item(t, "Keir Starmer", f"u{i}") for i, t in enumerate([
        "Stanislav Carpiuc: Man deported for role in arson plot targeting Keir Starmer",
        "Home Office Deports Stanislav Carpiuc After Arson Attacks Targeting Sir Keir Starmer",
        "Peter Mandelson vetting row deepens", "Peter Mandelson, the former ambassador, speaks out"])]
    service.save_profile({"slug": "keir-starmer", "media": media,
                          "wiki": {"status": "ok", "description": "Former PM", "daily_views": 20_000.0}})

    async def fake_wiki(person):
        if person["name"] == "Peter Mandelson":
            return {"status": "ok", "title": "Peter_Mandelson", "description": "British politician",
                    "url": "https://en.wikipedia.org/wiki/Peter_Mandelson", "daily_views": 3_000.0}
        return {"status": "none"}
    monkeypatch.setattr(sources, "wiki_person", fake_wiki)
    data = asyncio.run(service.build_people(roster))
    by_name = {r["name"]: r for r in data["people"]}
    assert list(by_name) == ["Keir Starmer", "Peter Mandelson", "Stanislav Carpiuc"]  # sorted by popularity
    assert by_name["Peter Mandelson"]["job"] == "British politician"  # Wikipedia beats a headline phrase
    assert by_name["Peter Mandelson"]["described_as"] == "former ambassador"
    assert by_name["Stanislav Carpiuc"]["popularity"]["tier"] == "Niche"
    assert by_name["Stanislav Carpiuc"]["job"] == ""  # no headline title, no article: left blank, not guessed
    service.save_people(data)
    assert service.people_list("ambassador")["people"][0]["name"] == "Peter Mandelson"
    assert service.people_list(watched=True)["total"] == 1
    # Private individuals stay out of the public list but remain in the local index.
    assert "Stanislav Carpiuc" not in {r["name"] for r in service.people_list()["people"]}
    assert "Stanislav Carpiuc" in {r["name"] for r in service.people_list(public=False)["people"]}


def test_people_endpoint_filters_and_cards_carry_popularity():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from lyra.api import watch_api

    service.save_people({"built_at": 1.0, "people": [
        {"name": "Keir Starmer", "slug": "keir-starmer", "watched": True, "job": "Former UK Prime Minister",
         "job_source": "watchlist", "mentions": 40, "companies": [], "tone": {"avg": 0, "label": "neutral"},
         "seen_with": ["Keir Starmer"], "popularity": {"score": 80, "tier": "Household name"}},
        {"name": "Andy Burnham", "slug": "", "watched": False, "job": "Britain PM", "job_source": "headline",
         "mentions": 5, "companies": [{"name": "Palantir", "ticker": "PLTR"}], "tone": {"avg": -0.3, "label": "negative"},
         "seen_with": ["Keir Starmer"], "popularity": {"score": 66, "tier": "Well known"},
         "wiki": {"status": "ok"}}]})
    app = FastAPI()
    app.include_router(watch_api.router)
    client = TestClient(app)
    assert [r["name"] for r in client.get("/api/watch/people").json()["people"]] == ["Keir Starmer", "Andy Burnham"]
    assert [r["name"] for r in client.get("/api/watch/people?watched=false").json()["people"]] == ["Andy Burnham"]
    assert client.get("/api/watch/people?q=palantir").json()["total"] == 1
    figures = client.get("/api/watch/figures").json()["figures"]
    starmer = next(f for f in figures if f["slug"] == "keir-starmer")
    assert starmer["popularity"]["score"] == 80 and starmer["media_mentions"] == 40


# Bugs found by the first live run over all 41 feeds.
@pytest.mark.parametrize("text,expected", [
    ("Saudi Crown Prince Mohammed Bin Salman hosts summit", ["Mohammed bin Salman"]),
    ("Trimming DraftKings and adding Robinhood, says fund", []),
    ("Iran RBC-Ukraine talks stall", []),
    ("Elysee Presidential palace denies report", []),
    ("Florida Phoenix reports on the budget", []),
    ("Narendra Modi Noida airport opening draws crowds", ["Narendra Modi"]),
    ("Brain Spoiler: It Wasn’t Pretty", []),
    ("Pelosi Must Press Connie Chan on Anti-Israel Stance", ["Connie Chan"]),
])
def test_names_in_live_run_regressions(text, expected):
    assert people.names_in(text) == expected


def test_a_first_name_is_not_read_as_someone_elses_surname():
    roster = [{"slug": "taylor-swift", "name": "Taylor Swift", "role": "Musician"}]
    media = [_item("Elizabeth Taylor biopic casts a lead", "Taylor Swift", "e1"),
             _item("Elizabeth Taylor estate sues studio", "Taylor Swift", "e2"),
             _item("Taylor Swift tops the chart again", "Taylor Swift", "e3"),
             _item("Taylor Swift and Travis Kelce visit Ohio", "Taylor Swift", "e4")]
    idx = people.build_index(media, roster)
    assert idx["Elizabeth Taylor"]["mentions"] == 2
    assert idx["Taylor Swift"]["mentions"] == 2


def test_possessive_without_apostrophe_merges():
    roster = [{"slug": "mark-zuckerberg", "name": "Mark Zuckerberg", "role": "CEO, Meta Platforms"}]
    media = [_item("Mark Zuckerbergs new glasses flop", "Mark Zuckerberg", "z1"),
             _item("Mark Zuckerbergs Meta cuts staff", "Mark Zuckerberg", "z2"),
             _item("Mark Zuckerberg testifies", "Mark Zuckerberg", "z3")]
    idx = people.build_index(media, roster)
    assert "Mark Zuckerbergs" not in idx and idx["Mark Zuckerberg"]["mentions"] == 3


def test_google_news_summary_echo_is_ignored():
    item = {"title": "Ex-Scottish Leader meets Humza Yousaf - Novara Media", "source": "Novara Media",
            "summary": "Ex-Scottish Leader meets Humza Yousaf Novara Media", "url": "https://n", "published": 1.79e9,
            "sentiment": 0.0, "companies": []}
    [m] = service._media([item], {"name": "Keir Starmer"})
    assert m["summary"] == "" and m["people"] == ["Humza Yousaf"]


@pytest.mark.parametrize("text,expected", [
    ("Chip Stock rally lifts Nasdaq", []),
    ("Ellison Debt pile grows at Paramount", []),
    ("JPMorgan Chase beats estimates", []),
    ("David DePape won’t face more charges for assaulting Paul Pelosi", ["David DePape", "Paul Pelosi"]),
    ("Wrexham co-owner Rob McElhenney speaks out", ["Rob McElhenney"]),
])
def test_words_after_a_first_name_need_to_be_surnames(text, expected):
    assert people.names_in(text) == expected


def test_spellings_of_one_person_merge(monkeypatch):
    roster = [{"slug": "friedrich-merz", "name": "Friedrich Merz", "role": "Chancellor of Germany"}]
    media = [_item(t, "Friedrich Merz", f"v{i}", s) for i, (t, s) in enumerate([
        ("Volodymyr Zelensky meets Friedrich Merz", 0.4), ("Volodymyr Zelensky thanks Berlin", 0.4),
        ("Volodymyr Zelenskyy asks for air defence", -0.2), ("Volodymyr Zelenskyy visits the front", -0.2),
        ("Flávio Bolsonaro speaks", 0.0), ("Flávio Bolsonaro again", 0.0), ("Flavio Bolsonaro once more", 0.0)])]
    service.save_profile({"slug": "friedrich-merz", "media": media, "wiki": {"status": "none"}})

    async def fake_wiki(person):
        if "Zelensk" in person["name"]:
            return {"status": "ok", "title": "Volodymyr_Zelenskyy", "description": "President of Ukraine",
                    "url": "", "daily_views": 50_000.0}
        return {"status": "none"}
    monkeypatch.setattr(sources, "wiki_person", fake_wiki)
    by_name = {r["name"]: r for r in asyncio.run(service.build_people(roster))["people"]}
    z = by_name["Volodymyr Zelensky"]
    assert z["mentions"] == 4 and z["also_known_as"] == ["Volodymyr Zelenskyy"] and "Volodymyr Zelenskyy" not in by_name
    assert z["tone"]["avg"] == 0.1 and z["job"] == "President of Ukraine"
    assert by_name["Flávio Bolsonaro"]["mentions"] == 3 and "Flavio Bolsonaro" not in by_name
