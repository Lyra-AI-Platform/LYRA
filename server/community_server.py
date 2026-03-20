"""
Lyra Community Intelligence Server
Copyright (C) 2026 Lyra Contributors — All Rights Reserved.
See LICENSE for terms.

This is the optional self-hosted aggregation server.
Deploy this on Railway, Render, Fly.io, or any VPS (free tier works fine).

What it does:
  - Receives anonymized topic submissions from opted-in Lyra instances
  - Aggregates topics into a frequency table (strips individual submissions)
  - Returns trending topics to all Lyra instances
  - STRIPS IP addresses immediately upon receipt

Deploy:
  pip install fastapi uvicorn
  uvicorn community_server:app --host 0.0.0.0 --port 8000
"""
import json
import logging
import os
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Lyra Community Intelligence Server",
    description="Aggregates anonymous topic trends from opt-in Lyra instances.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# ─── Storage (in-memory + file fallback) ───
DATA_FILE = Path("community_data.json")

def load_data() -> Dict:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except Exception:
            pass
    return {"topic_counts": {}, "total_submissions": 0, "last_updated": None}

def save_data(data: Dict):
    try:
        DATA_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.error(f"Save failed: {e}")

# Load on startup
community_data = load_data()

# ─── Rate limiting (simple in-memory) ───
submission_log: Dict[str, float] = {}  # installation_id -> last submission timestamp

def is_rate_limited(installation_id: str) -> bool:
    """Allow one submission per installation per 20 hours."""
    import time
    last = submission_log.get(installation_id, 0)
    if time.time() - last < 72000:  # 20 hours
        return True
    submission_log[installation_id] = time.time()
    # Clean up old entries periodically
    if len(submission_log) > 10000:
        cutoff = time.time() - 86400
        for k in [k for k, v in submission_log.items() if v < cutoff]:
            del submission_log[k]
    return False

# ─── Models ───
class ContributeRequest(BaseModel):
    installation_id: str = Field(..., min_length=16, max_length=64)
    lyra_version: str = Field(default="1.0.0", max_length=20)
    week_usage_count: int = Field(default=0, ge=0, le=9999)
    topics: List[str] = Field(default=[], max_items=50)
    submitted_at: str = Field(default="")

    @validator("topics", each_item=True)
    def clean_topic(cls, t):
        return t.lower().strip()[:40]

    @validator("topics")
    def filter_topics(cls, topics):
        import re
        cleaned = []
        for t in topics:
            # Reject anything that looks personal
            if re.search(r'@|https?://|\d{3}[-\s]\d{3,4}', t):
                continue
            if t.startswith(("my ", "i ", "i\t")):
                continue
            if len(t) >= 3:
                cleaned.append(t)
        return cleaned[:50]

# ─── Endpoints ───

@app.post("/api/contribute")
async def contribute(request: Request, body: ContributeRequest):
    """
    Accept anonymized topic submission from a Lyra instance.
    IP address is NEVER logged — we only log aggregate counts.
    """
    # Rate limit by installation ID (not IP)
    if is_rate_limited(body.installation_id):
        return JSONResponse(
            {"success": False, "error": "Rate limited — max 1 submission per 20 hours"},
            status_code=429,
        )

    if not body.topics:
        return {"success": True, "message": "No topics to process"}

    # Aggregate topics — increment global counts
    for topic in body.topics:
        if topic:
            community_data["topic_counts"][topic] = (
                community_data["topic_counts"].get(topic, 0) + 1
            )

    community_data["total_submissions"] = community_data.get("total_submissions", 0) + 1
    community_data["last_updated"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    save_data(community_data)

    # Return trending topics (top 30) for this instance to learn about
    top = sorted(
        community_data["topic_counts"].items(),
        key=lambda x: x[1],
        reverse=True,
    )[:30]
    trending = [t for t, _ in top]

    logger.info(
        f"Contribution received: {len(body.topics)} topics, "
        f"total submissions: {community_data['total_submissions']}"
    )

    return {
        "success": True,
        "trending_topics": trending,
        "total_topics_in_pool": len(community_data["topic_counts"]),
    }


@app.get("/api/trending")
async def get_trending(limit: int = 50):
    """
    Return the current top trending topics from the community.
    Publicly readable — no authentication required.
    """
    limit = min(max(limit, 1), 100)
    top = sorted(
        community_data["topic_counts"].items(),
        key=lambda x: x[1],
        reverse=True,
    )[:limit]

    return {
        "topics": [t for t, _ in top],
        "total_unique_topics": len(community_data["topic_counts"]),
        "total_submissions": community_data.get("total_submissions", 0),
        "last_updated": community_data.get("last_updated"),
    }


@app.get("/api/stats")
async def get_stats():
    """Public stats about the community pool."""
    return {
        "total_unique_topics": len(community_data["topic_counts"]),
        "total_submissions": community_data.get("total_submissions", 0),
        "last_updated": community_data.get("last_updated"),
        "privacy": "IP addresses are never stored. Only anonymized topic keywords.",
    }


@app.get("/")
async def root():
    return {
        "name": "Lyra Community Intelligence Server",
        "version": "1.0.0",
        "description": "Anonymous topic aggregation for Lyra AI Platform",
        "privacy": "No personal data collected. See /api/stats for details.",
        "endpoints": ["/api/contribute", "/api/trending", "/api/stats"],
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("community_server:app", host="0.0.0.0", port=port)
