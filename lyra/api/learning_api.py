"""
NEXUS Auto-Learning API
Endpoints to control and monitor NEXUS's autonomous learning system.
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
    return {"status": "started", "message": "NEXUS is now learning autonomously"}


@router.post("/stop")
async def stop_learning():
    """Stop autonomous background learning."""
    auto_learner.stop()
    return {"status": "stopped", "message": "Auto-learning paused"}


@router.post("/topic")
async def add_topic(request: AddTopicRequest):
    """Manually add a topic for NEXUS to learn about."""
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
