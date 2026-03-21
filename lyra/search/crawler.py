"""
Lyra AI Platform — Autonomous Web Crawler
Copyright (C) 2026 Lyra Contributors
Licensed under the Lyra Community License v1.0. See LICENSE for details.

Crawls web pages, Wikipedia (via Wikimedia JSON API), RSS feeds, and extracts
clean knowledge. Used by the auto-learner background system.

Wikipedia Best Practice: All Wikipedia data is fetched via the Wikimedia
Action API returning JSON — never by scraping HTML. This is faster, more
reliable, and respects Wikipedia's preferred access method.
  API docs: https://www.mediawiki.org/wiki/API:Main_page
"""
import asyncio
import hashlib
import logging
import re
from typing import List, Dict, Any, Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)

# Wikimedia API endpoint — JSON only, no HTML scraping
WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_HEADERS = {
    "User-Agent": "Lyra-AI/1.0 (https://github.com/Lyra-AI-Platform/LYRA; autonomous knowledge learner)",
    "Accept": "application/json",
}

# Wikipedia "Vital Articles" — the most important topics across all domains
# Used for bulk knowledge seeding via crawl_vital_articles()
WIKIPEDIA_VITAL_TOPICS = [
    # Mathematics
    "Mathematics", "Algebra", "Calculus", "Geometry", "Statistics",
    "Number theory", "Linear algebra", "Differential equations", "Probability",
    "Graph theory", "Topology", "Set theory",
    # Physics
    "Physics", "Classical mechanics", "Quantum mechanics", "General relativity",
    "Special relativity", "Thermodynamics", "Electromagnetism", "Optics",
    "Nuclear physics", "Particle physics", "String theory", "Black hole",
    "Dark matter", "Gravitational wave",
    # Chemistry
    "Chemistry", "Periodic table", "Chemical bond", "Organic chemistry",
    "Biochemistry", "Electrochemistry", "Thermochemistry", "Polymer",
    # Biology
    "Biology", "Cell biology", "Genetics", "Evolution", "Ecology",
    "Neuroscience", "Molecular biology", "Microbiology", "Anatomy",
    "Immunology", "Virology", "Botany", "Zoology", "Human genome",
    # Computer Science & AI
    "Computer science", "Artificial intelligence", "Machine learning",
    "Deep learning", "Neural network", "Natural language processing",
    "Computer vision", "Reinforcement learning", "Algorithm", "Data structure",
    "Operating system", "Computer network", "Cryptography", "Database",
    "Quantum computing", "Large language model", "Transformer (machine learning)",
    # Medicine & Health
    "Medicine", "Anatomy", "Pharmacology", "Epidemiology", "Cancer",
    "Vaccine", "Antibiotic", "Surgery", "Neurology", "Cardiology",
    "CRISPR", "Stem cell", "Gene therapy",
    # History
    "World history", "Ancient history", "Middle Ages", "Renaissance",
    "Industrial Revolution", "World War I", "World War II",
    "Cold War", "French Revolution", "Roman Empire", "Ancient Greece",
    # Philosophy
    "Philosophy", "Ethics", "Epistemology", "Metaphysics", "Logic",
    "Philosophy of mind", "Political philosophy", "Aesthetics",
    "Utilitarianism", "Existentialism", "Consciousness",
    # Economics
    "Economics", "Macroeconomics", "Microeconomics", "Game theory",
    "Behavioral economics", "Monetary policy", "Capitalism", "Globalization",
    # Geography & Environment
    "Climate change", "Plate tectonics", "Ocean current", "Biome",
    "Renewable energy", "Biodiversity", "Deforestation", "Water cycle",
    # Space & Astronomy
    "Astronomy", "Solar System", "Galaxy", "Big Bang", "Cosmology",
    "Space exploration", "Mars", "Exoplanet", "Telescope",
    # Society & Politics
    "Democracy", "Human rights", "International law", "Geopolitics",
    "Sociology", "Anthropology", "Psychology", "Linguistics",
]


class LyraCrawler:
    """
    Multi-source web crawler for autonomous knowledge gathering.

    Wikipedia access uses the Wikimedia JSON API exclusively:
      - action=query with prop=extracts for full article text (plain text, no HTML)
      - action=query with prop=links|categories for topic discovery
      - action=query with list=search for article lookup by topic
    All other web sources use httpx + BeautifulSoup for HTML parsing.
    """

    # RSS feeds for auto news ingestion
    DEFAULT_RSS_FEEDS = [
        "https://news.ycombinator.com/rss",
        "https://feeds.bbci.co.uk/news/technology/rss.xml",
        "https://rss.arxiv.org/rss/cs.AI",
        "https://rss.arxiv.org/rss/cs.LG",
        "https://rss.arxiv.org/rss/cs.CR",
        "https://feeds.feedburner.com/TechCrunch",
    ]

    def __init__(self):
        self._visited: set = set()

    # ─── Main Entry Point ───

    async def crawl_topic(self, topic: str, depth: int = 1) -> List[Dict[str, Any]]:
        """Crawl the web for a topic. Returns list of knowledge chunks."""
        results = []

        # 1. Wikipedia via JSON API (highest quality, always first)
        wiki_results = await self.crawl_wikipedia_full(topic)
        results.extend(wiki_results)

        # 2. DuckDuckGo web results
        search_results = await self.search_and_crawl(topic, max_pages=5)
        results.extend(search_results)

        logger.info(f"Crawled topic '{topic}': {len(results)} chunks")
        return results

    # ─── Wikimedia JSON API ───

    async def crawl_wikipedia_full(self, topic: str) -> List[Dict[str, Any]]:
        """
        Fetch Wikipedia article via Wikimedia JSON API.
        Returns multiple chunks: intro + all sections + discovered related topics.

        Uses API best practice: JSON format, action=query, prop=extracts|links|categories
        No HTML scraping — all data is plain text from the API.
        """
        try:
            import httpx
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:

                # Step 1: Search for the best matching article (JSON API)
                page_title = await self._wiki_search(client, topic)
                if not page_title:
                    return []

                # Step 2: Fetch full plain-text extract + metadata (JSON API)
                article = await self._wiki_fetch_article(client, page_title, topic)
                if not article:
                    return []

                results = [article]

                # Step 3: Discover related topics from links + categories (JSON API)
                related = await self._wiki_discover_related(client, page_title)
                article["related_topics"] = related[:10]

                return results

        except Exception as e:
            logger.debug(f"Wikipedia API crawl failed for '{topic}': {e}")
            return []

    async def _wiki_search(self, client, topic: str) -> Optional[str]:
        """
        Search Wikipedia for the best article matching a topic.
        Uses: action=query&list=search&format=json
        """
        try:
            params = {
                "action": "query",
                "list": "search",
                "srsearch": topic,
                "srlimit": 3,
                "srinfo": "totalhits",
                "srprop": "snippet|titlesnippet",
                "format": "json",
                "formatversion": "2",
            }
            resp = await client.get(WIKI_API, params=params, headers=WIKI_HEADERS)
            data = resp.json()
            results = data.get("query", {}).get("search", [])
            return results[0]["title"] if results else None
        except Exception as e:
            logger.debug(f"Wiki search failed: {e}")
            return None

    async def _wiki_fetch_article(
        self, client, page_title: str, topic: str
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch full article content via Wikimedia JSON API.
        Uses: action=query&prop=extracts&explaintext=true&format=json
        Returns plain text — no HTML parsing needed.
        """
        try:
            params = {
                "action": "query",
                "titles": page_title,
                "prop": "extracts|info",
                "exintro": False,         # Get full article, not just intro
                "explaintext": True,      # Plain text, not HTML ← key best practice
                "exsectionformat": "wiki", # Preserve section structure
                "inprop": "url|displaytitle",
                "format": "json",
                "formatversion": "2",
            }
            resp = await client.get(WIKI_API, params=params, headers=WIKI_HEADERS)
            data = resp.json()

            pages = data.get("query", {}).get("pages", [])
            if not pages:
                return None

            page = pages[0]
            extract = page.get("extract", "")
            title = page.get("title", page_title)
            url = page.get("fullurl", f"https://en.wikipedia.org/wiki/{quote(page_title.replace(' ', '_'))}")

            if not extract or len(extract) < 200:
                return None

            # Split into chunks at section boundaries (== Section ==)
            chunks = self._chunk_wiki_text(extract, max_chars=6000)
            main_chunk = chunks[0] if chunks else extract[:6000]

            logger.info(f"Wikipedia API: fetched '{title}' ({len(extract)} chars, {len(chunks)} sections)")

            return {
                "source": "wikipedia",
                "title": title,
                "url": url,
                "content": main_chunk,
                "topic": topic,
                "quality": "high",
                "full_chunks": chunks,       # All sections stored separately
                "char_count": len(extract),
            }
        except Exception as e:
            logger.debug(f"Wiki fetch failed for '{page_title}': {e}")
            return None

    async def _wiki_discover_related(
        self, client, page_title: str
    ) -> List[str]:
        """
        Discover related topics from a Wikipedia article's links and categories.
        Uses: action=query&prop=links|categories&format=json
        This feeds the auto-learner with new topics to explore.
        """
        related = []
        try:
            params = {
                "action": "query",
                "titles": page_title,
                "prop": "links|categories",
                "pllimit": 20,       # Top 20 linked articles
                "cllimit": 10,       # Top 10 categories
                "plnamespace": 0,    # Main article namespace only
                "format": "json",
                "formatversion": "2",
            }
            resp = await client.get(WIKI_API, params=params, headers=WIKI_HEADERS)
            data = resp.json()

            pages = data.get("query", {}).get("pages", [])
            if pages:
                page = pages[0]
                # Extract linked article titles as related topics
                links = page.get("links", [])
                related.extend([l["title"] for l in links[:15]])
                # Extract category names (strip "Category:" prefix)
                cats = page.get("categories", [])
                for c in cats[:5]:
                    cat = c["title"].replace("Category:", "").strip()
                    if len(cat) > 3 and "stub" not in cat.lower():
                        related.append(cat)

        except Exception as e:
            logger.debug(f"Wiki related discovery failed: {e}")

        return related

    async def crawl_wikipedia_by_title(
        self, title: str, topic: str = ""
    ) -> List[Dict[str, Any]]:
        """Crawl a specific Wikipedia article by exact title."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=20) as client:
                article = await self._wiki_fetch_article(client, title, topic or title)
                if article:
                    related = await self._wiki_discover_related(client, title)
                    article["related_topics"] = related
                    return [article]
        except Exception as e:
            logger.debug(f"Wiki title crawl failed '{title}': {e}")
        return []

    async def crawl_vital_articles(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Crawl Wikipedia's most important articles to seed broad knowledge.
        Uses the curated WIKIPEDIA_VITAL_TOPICS list covering all major domains.
        """
        results = []
        topics = WIKIPEDIA_VITAL_TOPICS[:limit]
        logger.info(f"Seeding knowledge from {len(topics)} Wikipedia vital articles")

        for i, topic in enumerate(topics):
            if i > 0 and i % 5 == 0:
                await asyncio.sleep(1)  # Respectful rate limiting
            try:
                articles = await self.crawl_wikipedia_full(topic)
                results.extend(articles)
                if articles:
                    logger.info(f"Vital article [{i+1}/{len(topics)}]: '{topic}' — {articles[0].get('char_count', 0)} chars")
            except Exception as e:
                logger.debug(f"Vital article failed '{topic}': {e}")

        return results

    # ─── Web Search + Crawl ───

    async def search_and_crawl(
        self, topic: str, max_pages: int = 5
    ) -> List[Dict[str, Any]]:
        """Search DuckDuckGo and crawl top results."""
        results = []
        try:
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS

            loop = asyncio.get_event_loop()

            def _search():
                with DDGS() as ddgs:
                    return list(ddgs.text(topic, max_results=max_pages + 2))

            raw = await loop.run_in_executor(None, _search)

            for item in raw[:max_pages]:
                url = item.get("href", "")
                if not url or self._is_visited(url):
                    continue
                # Skip Wikipedia HTML — use the API instead
                if "wikipedia.org/wiki" in url:
                    continue

                content = await self._fetch_clean(url)
                if content and len(content) > 800:
                    results.append({
                        "source": "web",
                        "title": item.get("title", url),
                        "url": url,
                        "content": content[:6000],
                        "snippet": item.get("body", "")[:300],
                        "topic": topic,
                        "quality": "medium",
                    })
                    self._mark_visited(url)

        except ImportError:
            logger.warning("ddgs / duckduckgo-search not available")
        except Exception as e:
            logger.debug(f"Search crawl failed: {e}")

        return results

    # ─── RSS Feeds ───

    async def crawl_rss_feeds(
        self, feeds: List[str] = None
    ) -> List[Dict[str, Any]]:
        """Crawl RSS feeds for fresh news/articles."""
        feeds = feeds or self.DEFAULT_RSS_FEEDS
        results = []
        for feed_url in feeds:
            try:
                items = await self._parse_rss(feed_url)
                results.extend(items)
            except Exception as e:
                logger.debug(f"RSS fetch failed {feed_url}: {e}")
        return results

    async def _parse_rss(self, url: str) -> List[Dict[str, Any]]:
        """Parse an RSS/Atom feed and return items."""
        try:
            import httpx
            from xml.etree import ElementTree as ET

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers=WIKI_HEADERS)
                root = ET.fromstring(resp.text)

            items = []
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            entries = root.findall(".//item") or root.findall(".//atom:entry", ns)

            for entry in entries[:10]:
                title_el = entry.find("title")
                link_el = entry.find("link")
                desc_el = entry.find("description") or entry.find("summary")

                title = title_el.text if title_el is not None else ""
                link = link_el.text if link_el is not None else ""
                desc = desc_el.text if desc_el is not None else ""
                desc = re.sub(r"<[^>]+>", " ", desc or "").strip()

                if title and (link or desc):
                    items.append({
                        "source": "rss",
                        "title": title,
                        "url": link,
                        "content": f"{title}\n\n{desc}",
                        "topic": "news",
                        "quality": "medium",
                    })
            return items
        except Exception as e:
            logger.debug(f"RSS parse error: {e}")
            return []

    # ─── Direct URL Crawl ───

    async def crawl_url(self, url: str, topic: str = "") -> Optional[Dict[str, Any]]:
        """Crawl a specific URL. Uses Wikipedia JSON API if it's a Wikipedia URL."""
        # Route Wikipedia URLs through the JSON API, not HTML scraping
        wiki_match = re.match(r"https?://en\.wikipedia\.org/wiki/(.+)", url)
        if wiki_match:
            page_title = wiki_match.group(1).replace("_", " ")
            results = await self.crawl_wikipedia_by_title(page_title, topic)
            return results[0] if results else None

        content = await self._fetch_clean(url)
        if not content:
            return None
        return {
            "source": "direct",
            "title": url,
            "url": url,
            "content": content[:6000],
            "topic": topic or url,
            "quality": "medium",
        }

    # ─── HTML Fetch (non-Wikipedia only) ───

    async def _fetch_clean(self, url: str) -> str:
        """Fetch URL and extract clean readable text using BeautifulSoup."""
        try:
            import httpx
            from bs4 import BeautifulSoup

            async with httpx.AsyncClient(
                timeout=12, follow_redirects=True, verify=False
            ) as client:
                headers = {"User-Agent": "Mozilla/5.0 (compatible; Lyra-AI/1.0)"}
                resp = await client.get(url, headers=headers)
                if resp.status_code != 200:
                    return ""

                ct = resp.headers.get("content-type", "")
                if "text/html" not in ct and "text/plain" not in ct:
                    return ""

                soup = BeautifulSoup(resp.text, "html.parser")
                for tag in soup(["script", "style", "nav", "footer", "header",
                                  "aside", "form", "iframe", "noscript"]):
                    tag.decompose()

                main = (
                    soup.find("main") or soup.find("article")
                    or soup.find(id="content") or soup.find(class_="content")
                    or soup.find(class_="post-content") or soup.body
                )
                text = main.get_text(separator=" ", strip=True) if main else soup.get_text(separator=" ", strip=True)
                return re.sub(r"\s+", " ", text).strip()

        except Exception as e:
            logger.debug(f"Fetch failed {url}: {e}")
            return ""

    # ─── Text Chunking ───

    def _chunk_wiki_text(self, text: str, max_chars: int = 6000) -> List[str]:
        """
        Split Wikipedia plain text into chunks at section boundaries.
        Wikipedia sections are marked with == Section == headers in plain text.
        """
        # Split on section headers
        sections = re.split(r"\n==+\s*.+?\s*==+\n", text)
        chunks = []
        current = ""

        for section in sections:
            section = section.strip()
            if not section:
                continue
            if len(current) + len(section) < max_chars:
                current += "\n\n" + section
            else:
                if current.strip():
                    chunks.append(current.strip())
                current = section

        if current.strip():
            chunks.append(current.strip())

        # Further split any chunks that are still too large
        final_chunks = []
        for chunk in chunks:
            if len(chunk) <= max_chars:
                final_chunks.append(chunk)
            else:
                paragraphs = chunk.split("\n\n")
                sub = ""
                for p in paragraphs:
                    if len(sub) + len(p) < max_chars:
                        sub += "\n\n" + p
                    else:
                        if sub.strip():
                            final_chunks.append(sub.strip())
                        sub = p
                if sub.strip():
                    final_chunks.append(sub.strip())

        return final_chunks or [text[:max_chars]]

    def _chunk_text(self, text: str, max_chars: int = 4000) -> List[str]:
        """Generic text chunker at paragraph boundaries."""
        paragraphs = text.split("\n\n")
        chunks, current = [], ""
        for p in paragraphs:
            if len(current) + len(p) < max_chars:
                current += "\n\n" + p
            else:
                if current:
                    chunks.append(current.strip())
                current = p
        if current:
            chunks.append(current.strip())
        return chunks or [text[:max_chars]]

    def _is_visited(self, url: str) -> bool:
        return hashlib.md5(url.encode()).hexdigest() in self._visited

    def _mark_visited(self, url: str):
        self._visited.add(hashlib.md5(url.encode()).hexdigest())

    def reset_visited(self):
        self._visited.clear()


# Backward-compatible alias
NexusCrawler = LyraCrawler

# Global singleton
crawler = LyraCrawler()
