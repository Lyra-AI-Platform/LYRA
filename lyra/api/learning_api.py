"""

Copyright (C) 2026 Lyra Contributors
Licensed under the Lyra Community License v1.0. See LICENSE for details.
Lyra Auto-Learning API
Endpoints to control and monitor Lyra's autonomous learning system.
"""
import asyncio
import logging
from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from lyra.core.auto_learner import auto_learner

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/learning", tags=["learning"])


class AddTopicRequest(BaseModel):
    topic: str
    priority: int = 5


class CrawlNowRequest(BaseModel):
    topics: Optional[List[str]] = None


class SetIntervalRequest(BaseModel):
    interval_minutes: int


class FeedUrlRequest(BaseModel):
    url: str
    topic: str = ""


@router.get("/status")
async def get_status():
    """Get full auto-learning status and activity log."""
    return auto_learner.get_status()


@router.post("/start")
async def start_learning():
    """Enable and start autonomous background learning."""
    auto_learner.enabled = True
    auto_learner.start()
    return {"status": "started", "message": "Lyra is now learning autonomously"}


@router.post("/stop")
async def stop_learning():
    """Stop autonomous background learning."""
    auto_learner.stop()
    return {"status": "stopped", "message": "Auto-learning paused"}


@router.post("/topic")
async def add_topic(request: AddTopicRequest):
    """Manually add a topic for Lyra to learn about."""
    auto_learner.add_topic(request.topic, request.priority)
    return {
        "status": "added",
        "topic": request.topic,
        "priority": request.priority,
    }


@router.delete("/topic/{topic}")
async def remove_topic(topic: str):
    """Remove a topic from the learning queue."""
    topic_lower = topic.lower()
    if topic_lower in auto_learner.topic_scores:
        del auto_learner.topic_scores[topic_lower]
        auto_learner._save_state()
        return {"status": "removed", "topic": topic}
    return {"status": "not_found", "topic": topic}


@router.post("/crawl-now")
async def crawl_now(request: CrawlNowRequest, background_tasks: BackgroundTasks):
    """
    Trigger an immediate learning crawl.
    If topics provided, crawl those. Otherwise crawl top queued topics.
    """
    if request.topics:
        for topic in request.topics:
            auto_learner.add_topic(topic, priority=10)

    background_tasks.add_task(_run_immediate_crawl, request.topics)
    return {
        "status": "started",
        "message": f"Crawling now{'for: ' + ', '.join(request.topics) if request.topics else ''}",
    }


@router.post("/crawl-url")
async def crawl_url(request: FeedUrlRequest, background_tasks: BackgroundTasks):
    """Crawl a specific URL and store its knowledge."""
    background_tasks.add_task(_crawl_specific_url, request.url, request.topic)
    return {"status": "started", "url": request.url}


@router.post("/crawl-rss")
async def crawl_rss(background_tasks: BackgroundTasks):
    """Immediately crawl all RSS news feeds."""
    background_tasks.add_task(_crawl_rss_now)
    return {"status": "started", "message": "Crawling RSS feeds now"}


class SeedWikipediaRequest(BaseModel):
    limit: int = 50  # How many vital articles to crawl (max 100)


@router.post("/seed-wikipedia")
async def seed_wikipedia(request: SeedWikipediaRequest, background_tasks: BackgroundTasks):
    """
    Bulk-seed Lyra's knowledge from Wikipedia's most important articles.
    Uses the Wikimedia JSON API (not HTML scraping) across all major domains:
    mathematics, physics, biology, AI, history, philosophy, and more.
    """
    limit = max(1, min(request.limit, len(__import__('lyra.search.crawler', fromlist=['WIKIPEDIA_VITAL_TOPICS']).WIKIPEDIA_VITAL_TOPICS)))
    background_tasks.add_task(_seed_wikipedia_bg, limit)
    return {
        "status": "started",
        "message": f"Seeding knowledge from {limit} Wikipedia vital articles via JSON API",
        "note": "This runs in the background — check /api/learning/status for progress",
    }


async def _seed_wikipedia_bg(limit: int):
    """Background task: bulk crawl Wikipedia vital articles."""
    from lyra.search.crawler import crawler, WIKIPEDIA_VITAL_TOPICS
    from lyra.memory.vector_memory import memory

    auto_learner._log_activity(f"📚 Starting Wikipedia bulk seed: {limit} vital articles")
    topics = WIKIPEDIA_VITAL_TOPICS[:limit]
    total_stored = 0

    for i, topic in enumerate(topics):
        if i > 0 and i % 5 == 0:
            await asyncio.sleep(2)  # Respectful rate limiting

        try:
            auto_learner.current_activity = f"📖 Wikipedia: {topic} ({i+1}/{len(topics)})"
            articles = await crawler.crawl_wikipedia_full(topic)

            for article in articles:
                # Store all chunks of the article
                for j, chunk in enumerate(article.get("full_chunks", [article.get("content", "")])):
                    if len(chunk) < 200:
                        continue
                    stored = memory.store(
                        content=f"[WIKIPEDIA — {article['title']}]\nSource: {article['url']}\nTopic: {topic}\n\n{chunk}",
                        memory_type="learned_knowledge",
                        metadata={
                            "topic": topic,
                            "source": article["url"],
                            "source_type": "wikipedia_api",
                            "title": article["title"],
                            "quality": "high",
                            "chunk_index": str(j),
                        },
                    )
                    if stored:
                        total_stored += 1
                        auto_learner.learned_count += 1

                # Feed related topics into the learning queue
                for related in article.get("related_topics", [])[:5]:
                    auto_learner.topic_scores[related.lower()] += 2

            if articles:
                auto_learner._log_activity(
                    f"📖 [{i+1}/{len(topics)}] '{topic}': "
                    f"{sum(len(a.get('full_chunks', [])) for a in articles)} chunks stored"
                )

        except Exception as e:
            logger.error(f"Vital article failed '{topic}': {e}")

    auto_learner.crawl_count += 1
    auto_learner.current_activity = f"idle — Wikipedia seed done: {total_stored} facts"
    auto_learner._log_activity(f"✅ Wikipedia bulk seed complete: {total_stored} facts stored from {len(topics)} articles")
    auto_learner._save_state()


@router.post("/interval")
async def set_interval(request: SetIntervalRequest):
    """Change the auto-crawl interval in minutes."""
    minutes = max(5, min(request.interval_minutes, 1440))  # 5min - 24hr
    auto_learner.crawl_interval_seconds = minutes * 60
    return {"status": "updated", "interval_minutes": minutes}


@router.get("/topics")
async def get_topics():
    """Get all tracked topics with scores."""
    return {
        "topics": [
            {
                "topic": t,
                "score": s,
                "crawled": t in auto_learner.topic_last_crawled,
            }
            for t, s in auto_learner.topic_scores.most_common(100)
        ]
    }


@router.delete("/topics/clear")
async def clear_topics():
    """Clear all tracked topics."""
    auto_learner.topic_scores.clear()
    auto_learner.topic_last_crawled.clear()
    auto_learner._save_state()
    return {"status": "cleared"}


# ─── Background Tasks ───

async def _run_immediate_crawl(topics: Optional[List[str]]):
    """Run a crawl cycle immediately."""
    from lyra.search.crawler import crawler
    from lyra.memory.vector_memory import memory

    if topics:
        for topic in topics:
            await auto_learner._crawl_and_store(topic, crawler, memory)
    else:
        await auto_learner._learning_cycle()


async def _crawl_specific_url(url: str, topic: str):
    """Crawl a specific URL."""
    from lyra.search.crawler import crawler
    from lyra.memory.vector_memory import memory

    auto_learner.current_activity = f"🌐 Crawling URL: {url}"
    result = await crawler.crawl_url(url, topic)
    if result:
        content = result.get("content", "")
        if content:
            memory.store(
                content=f"[LEARNED FROM URL: {url}]\nTopic: {topic}\n\n{content}",
                memory_type="learned_knowledge",
                metadata={"topic": topic, "source": url, "source_type": "direct"},
            )
            auto_learner.learned_count += 1
            auto_learner._log_activity(f"🔗 Crawled URL: {url} ({len(content)} chars)")
    auto_learner.current_activity = "idle"


async def _crawl_rss_now():
    """Run RSS crawl immediately."""
    from lyra.search.crawler import crawler
    from lyra.memory.vector_memory import memory
    await auto_learner._crawl_rss(crawler, memory)
    auto_learner.current_activity = "idle"
