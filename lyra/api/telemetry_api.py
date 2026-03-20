"""
Lyra AI Platform — Telemetry API
Copyright (C) 2026 Lyra Contributors — All Rights Reserved.
See LICENSE for terms.

Endpoints to manage opt-in collective intelligence sharing.
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List
from lyra.telemetry.collector import telemetry

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])


class OptInRequest(BaseModel):
    server_url: Optional[str] = None


class TopicsRequest(BaseModel):
    topics: List[str]


@router.get("/status")
async def status():
    return telemetry.get_status()


@router.post("/opt-in")
async def opt_in(request: OptInRequest):
    result = telemetry.opt_in(request.server_url)
    telemetry.start()
    return result


@router.post("/opt-out")
async def opt_out():
    result = telemetry.opt_out()
    telemetry.stop()
    return result


@router.get("/trending")
async def get_trending():
    """Fetch current trending topics from the community server."""
    topics = await telemetry.fetch_community_topics()
    return {"topics": topics, "count": len(topics)}


@router.post("/sync-now")
async def sync_now():
    """Manually trigger a sync with the community server."""
    if not telemetry.enabled:
        return {"success": False, "message": "Telemetry is not enabled"}
    await telemetry._sync()
    return {"success": True}
