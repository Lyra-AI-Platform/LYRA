"""Lyra Web Crawler"""
import asyncio, logging
import httpx
from typing import List, Dict
logger = logging.getLogger(__name__)
class LyraCrawler:
    async def crawl_topic(self, topic: str) -> List[Dict]:
        try:
            from ddgs import DDGS
            with DDGS() as d:
                results = list(d.text(topic, max_results=3))
            chunks = []
            async with httpx.AsyncClient(timeout=10) as client:
                for r in results[:2]:
                    try:
                        resp = await client.get(r["href"])
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(resp.text, "html.parser")
                        text = " ".join(p.get_text() for p in soup.find_all("p"))[:2000]
                        if text: chunks.append({"topic": topic, "content": text, "source": r["href"]})
                    except: pass
            return chunks
        except Exception as e:
            logger.debug(f"Crawl error: {e}"); return []
crawler = LyraCrawler()
