"""Collects the newswire: GDELT (global, every language), publishers' feeds, Google News
editions, arXiv and OpenAlex research. Runs in the background for as long as Lyra runs.

One cycle: every GDELT topic and country sweep (through the same 6-second GDELT gate as Lyra
Watch, so the address is never rate-limited), every feed, and research every 30 minutes. A
source that fails is recorded and retried next cycle; it never stops the loop.
"""
import asyncio
import hashlib
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional
from urllib.parse import quote, urlparse

import httpx

from lyra.newswire import config as C
from lyra.newswire.store import get_wire

logger = logging.getLogger(__name__)
UA = "LyraNewswire/1.0 (+https://lyraauth.com; support@lyraauth.com)"
GDELT_DOC = ("https://api.gdeltproject.org/api/v2/doc/doc?query={q}&mode=artlist&format=json"
             "&maxrecords=250&sort=datedesc&timespan={span}")
RESEARCH_EVERY = 1800
# GDELT names countries in full; map the common ones to ISO codes for filtering.
GDELT_COUNTRY_NAMES = {
    "United States": "US", "United Kingdom": "GB", "Canada": "CA", "Australia": "AU", "India": "IN", "China": "CN",
    "Japan": "JP", "South Korea": "KR", "Taiwan": "TW", "Germany": "DE", "France": "FR", "Italy": "IT", "Spain": "ES",
    "Netherlands": "NL", "Switzerland": "CH", "Sweden": "SE", "Brazil": "BR", "Mexico": "MX", "Argentina": "AR",
    "South Africa": "ZA", "Nigeria": "NG", "Egypt": "EG", "Saudi Arabia": "SA", "United Arab Emirates": "AE",
    "Turkey": "TR", "Israel": "IL", "Russia": "RU", "Ukraine": "UA", "Poland": "PL", "Indonesia": "ID",
    "Singapore": "SG", "Malaysia": "MY", "Vietnam": "VN", "Philippines": "PH", "Thailand": "TH", "Pakistan": "PK",
    "Ireland": "IE", "Belgium": "BE", "Austria": "AT", "Norway": "NO", "Denmark": "DK", "Finland": "FI",
    "Portugal": "PT", "Greece": "GR", "Czech Republic": "CZ", "Hungary": "HU", "Romania": "RO", "New Zealand": "NZ",
    "Chile": "CL", "Colombia": "CO", "Peru": "PE", "Kenya": "KE", "Qatar": "QA", "Hong Kong": "HK", "Bangladesh": "BD",
    "Iran": "IR", "Iraq": "IQ", "Morocco": "MA", "Ghana": "GH", "Ethiopia": "ET",
}
LANG_CODES = {"English": "en", "German": "de", "French": "fr", "Spanish": "es", "Italian": "it", "Portuguese": "pt",
              "Japanese": "ja", "Chinese": "zh", "Korean": "ko", "Russian": "ru", "Arabic": "ar", "Turkish": "tr",
              "Dutch": "nl", "Polish": "pl", "Swedish": "sv", "Hindi": "hi", "Indonesian": "id", "Vietnamese": "vi",
              "Thai": "th", "Ukrainian": "uk", "Hebrew": "he", "Persian": "fa", "Greek": "el", "Czech": "cs",
              "Romanian": "ro", "Hungarian": "hu", "Malay": "ms", "Bengali": "bn", "Urdu": "ur", "Tamil": "ta"}

_COMPANY_RE = re.compile(r"(?<![A-Za-z])(" + "|".join(sorted((re.escape(k) for k in C.COMPANIES), key=len, reverse=True)) + r")(?![A-Za-z])")
AMBIGUOUS = {"Meta", "Shell", "Apple", "Olin", "Amazon", "Arm Holdings", "Sika", "Bayer", "Linde", "Total"}
_CASHTAG_RE = re.compile(r"(?:\$|\b(?:NYSE|NASDAQ|Nasdaq|LSE|TSX|ASX)\s*:\s*)([A-Z]{1,5}(?:[.-][A-Z])?)\b")


def item_id(url: str) -> str:
    return hashlib.sha1(url.split("#")[0].encode()).hexdigest()[:20]


class Tagger:
    """Topics, companies (tickers) and named people for one item."""

    def __init__(self):
        self.people: Dict[str, str] = {}
        self.loaded = 0.0

    def refresh_people(self):
        """Public figures known to Lyra Watch, matched by full name (two words or more)."""
        if time.time() - self.loaded < 3600:
            return
        try:
            from lyra.watch.service import is_public_figure, load_people
            from lyra.watch.config import load_roster
            names = {p["name"]: p.get("slug") or p["name"] for p in load_roster()}
            for r in load_people().get("people", []):
                if is_public_figure(r) and len(r.get("name", "").split()) >= 2:
                    names.setdefault(r["name"], r.get("id") or r["name"])
            self.people = names
            self._people_re = re.compile(r"(?<![A-Za-z])(" + "|".join(sorted((re.escape(n) for n in names), key=len, reverse=True)) + r")(?![A-Za-z])") if names else None
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Newswire: people list unavailable: {e}")
            self._people_re = None
        self.loaded = time.time()

    def tag(self, it: Dict) -> Dict:
        text = f"{it.get('title', '')} {it.get('summary', '')}"
        low = f" {text.lower()} "
        topics = set(it.get("topics", []))
        for topic, words in C.TOPIC_WORDS.items():
            if any(w in low for w in words):
                topics.add(topic)
        english = (it.get("language") or "en").startswith("en")
        # Names that are ordinary words elsewhere ("meta" is "goal" in Spanish and Italian).
        tickers = {C.COMPANIES[m] for m in _COMPANY_RE.findall(text) if english or m not in AMBIGUOUS}
        tickers |= {t for t in _CASHTAG_RE.findall(text) if len(t) > 1}
        people = set()
        if getattr(self, "_people_re", None):
            people = set(self._people_re.findall(text))
        return {**it, "topics": sorted(topics), "tickers": sorted(tickers), "people": sorted(people)}


tagger = Tagger()


class Collector:
    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self.last_span: Dict[str, float] = {}
        self.last_research = 0.0
        self.cycles = 0

    # ── sources ─────────────────────────────────────────────────────────────

    async def _gdelt(self, client: httpx.AsyncClient, key: str, query: str, topic: str = "", country: str = "") -> int:
        from lyra.watch import chatter
        last = self.last_span.get(key, 0)
        minutes = int(min(1440, max(15, (time.time() - last) / 60 + 5))) if last else 1440
        url = GDELT_DOC.format(q=quote(query), span=f"{minutes}min")
        async with chatter._gdelt_gate:
            wait = chatter._gdelt_state["next"] - time.time()
            if wait > 30:
                return 0
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                r = await client.get(url, timeout=40)
                body = r.text
            except httpx.HTTPError as e:
                body = ""
                get_wire().run(f"gdelt:{key}", error=str(e))
            if not body.lstrip().startswith("{"):
                chatter._gdelt_state["refusals"] += 1
                chatter._gdelt_state["next"] = time.time() + min(1800, 60 * 2 ** (chatter._gdelt_state["refusals"] - 1))
                return 0
            chatter._gdelt_state.update(refusals=0, last_ok=time.time(), next=time.time() + chatter.GDELT_INTERVAL)
        try:
            rows = json.loads(body).get("articles", [])
        except ValueError:
            return 0
        items = []
        for a in rows:
            if not a.get("url") or not a.get("title"):
                continue
            try:
                when = datetime.strptime(a.get("seendate", ""), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).timestamp()
            except ValueError:
                when = time.time()
            items.append(tagger.tag({
                "id": item_id(a["url"]), "url": a["url"], "title": a["title"].strip(), "source": a.get("domain", ""),
                "country": country or GDELT_COUNTRY_NAMES.get(a.get("sourcecountry", ""), ""),
                "language": LANG_CODES.get(a.get("language", ""), (a.get("language") or "")[:2].lower()),
                "kind": "news", "topics": [topic] if topic else [], "published": when, "via": "GDELT"}))
        added = get_wire().add(items)
        get_wire().run(f"gdelt:{key}", added)
        self.last_span[key] = time.time()
        return added

    async def _rss(self, client: httpx.AsyncClient, url: str, country: str, lang: str, key: str = "") -> int:
        from lyra.market.news import parse_feed
        try:
            r = await client.get(url, timeout=20)
            r.raise_for_status()
        except httpx.HTTPError as e:
            get_wire().run(key or url, error=str(e))
            return 0
        items = [tagger.tag({"id": item_id(i["url"]), "url": i["url"], "title": i["title"], "summary": i.get("summary", "")[:400],
                             "source": urlparse(i["url"]).netloc.replace("www.", "") if "news.google" not in i["url"] else (i.get("source") or ""),
                             "country": country, "language": lang, "kind": "news",
                             "published": i.get("published") or time.time(), "via": "RSS"})
                 for i in parse_feed(r.text)]
        added = get_wire().add(items)
        get_wire().run(key or url, added)
        return added

    async def _arxiv(self, client: httpx.AsyncClient) -> int:
        total = 0
        for topic, cats in C.ARXIV_CATEGORIES.items():
            q = "+OR+".join(f"cat:{c}" for c in cats)
            try:
                r = await client.get(C.ARXIV.format(q=q), timeout=40)
                r.raise_for_status()
                root = ET.fromstring(r.text)
            except (httpx.HTTPError, ET.ParseError) as e:
                get_wire().run(f"arxiv:{topic}", error=str(e))
                continue
            ns = {"a": "http://www.w3.org/2005/Atom"}
            items = []
            for e in root.findall("a:entry", ns):
                url = (e.findtext("a:id", "", ns) or "").strip()
                title = " ".join((e.findtext("a:title", "", ns) or "").split())
                if not url or not title:
                    continue
                pub = e.findtext("a:published", "", ns)
                try:
                    when = datetime.fromisoformat(pub.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    when = time.time()
                summary = " ".join((e.findtext("a:summary", "", ns) or "").split())[:400]
                items.append(tagger.tag({"id": item_id(url), "url": url, "title": title, "summary": summary, "source": "arxiv.org",
                                         "country": "", "language": "en", "kind": "research", "topics": [topic],
                                         "published": when, "via": "arXiv"}))
            added = get_wire().add(items)
            get_wire().run(f"arxiv:{topic}", added)
            total += added
            await asyncio.sleep(3.5)   # arXiv asks for a pause between calls
        return total

    async def _openalex(self, client: httpx.AsyncClient) -> int:
        since = (date.today() - timedelta(days=14)).isoformat()
        total = 0
        for topic, searches in C.OPENALEX_SEARCHES.items():
            for s in searches:
                try:
                    r = await client.get(C.OPENALEX.format(q=quote(s), since=since), timeout=40)
                    r.raise_for_status()
                    rows = r.json().get("results", [])
                except (httpx.HTTPError, ValueError) as e:
                    get_wire().run(f"openalex:{s}", error=str(e))
                    continue
                items = []
                for w in rows:
                    url = w.get("doi") or w.get("id")
                    title = " ".join((w.get("title") or "").split())
                    if not url or not title:
                        continue
                    venue = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or "journal"
                    authors = [a.get("author", {}).get("display_name") for a in (w.get("authorships") or [])[:3]]
                    try:
                        when = datetime.fromisoformat(w.get("publication_date", "")).replace(tzinfo=timezone.utc).timestamp()
                    except ValueError:
                        when = time.time()
                    items.append(tagger.tag({"id": item_id(url), "url": url, "title": title,
                                             "summary": f"{venue}. " + ", ".join(a for a in authors if a),
                                             "source": venue[:120], "country": "", "language": (w.get("language") or "en")[:2],
                                             "kind": "research", "topics": [topic], "published": when, "via": "OpenAlex"}))
                added = get_wire().add(items)
                get_wire().run(f"openalex:{s}", added)
                total += added
                await asyncio.sleep(0.5)
        return total

    # ── loop ────────────────────────────────────────────────────────────────

    async def cycle(self):
        tagger.refresh_people()
        added = 0
        async with httpx.AsyncClient(headers={"User-Agent": UA}, follow_redirects=True) as client:
            feeds = [self._rss(client, u, c, l) for u, c, l in C.RSS_FEEDS]
            for gl, lang in C.GOOGLE_EDITIONS:
                hl = f"{lang}-{gl}" if lang != "en" or gl != "US" else "en-US"
                feeds.append(self._rss(client, C.GOOGLE_EDITION.format(hl=hl, gl=gl, lang=lang), gl, lang, f"google:{gl}"))
                for topic in ("BUSINESS", "TECHNOLOGY", "SCIENCE"):
                    feeds.append(self._rss(client, C.GOOGLE_TOPIC.format(topic=topic, hl=hl, gl=gl, lang=lang), gl, lang,
                                           f"google:{gl}:{topic.lower()}"))
            sem = asyncio.Semaphore(6)

            async def limited(coro):
                async with sem:
                    return await coro
            added += sum(await asyncio.gather(*(limited(f) for f in feeds)))
            for topic, q in C.GDELT_TOPICS.items():
                added += await self._gdelt(client, f"topic:{topic}", q, topic=topic)
            for fips, iso in C.GDELT_COUNTRIES.items():
                added += await self._gdelt(client, f"country:{iso}", f"{C.COUNTRY_QUERY} sourcecountry:{fips}", country=iso)
            if time.time() - self.last_research > RESEARCH_EVERY:
                added += await self._arxiv(client) + await self._openalex(client)
                self.last_research = time.time()
        self.cycles += 1
        if self.cycles % 50 == 1:
            get_wire().prune()
        logger.info(f"Newswire: +{added} items this cycle")
        return added

    async def _run(self):
        await asyncio.sleep(20)   # let the rest of Lyra start first
        while True:
            try:
                await self.cycle()
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Newswire cycle failed, retrying in two minutes: {e}")
                await asyncio.sleep(120)

    def alive(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self):
        if not self.alive():
            self._task = asyncio.get_event_loop().create_task(self._run())

    def stop(self):
        if self._task:
            self._task.cancel()


collector = Collector()
