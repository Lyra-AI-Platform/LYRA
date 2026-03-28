"""
Lyra AI Platform — Autonomous Cognition API
Copyright (C) 2026 Lyra Contributors
Licensed under the Lyra Community License v1.0. See LICENSE for details.

REST + WebSocket endpoints for monitoring and controlling
the autonomous self-directed cognition loop.
"""
import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from lyra.core.cognition_engine import cognition_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cognition", tags=["cognition"])


class InjectRequest(BaseModel):
    question: str
    priority: int = 10


@router.get("/status")
async def get_cognition_status():
    """Full status of the autonomous cognition loop."""
    return cognition_engine.get_status()


@router.post("/start")
async def start_cognition():
    """Start the autonomous cognition loop."""
    if cognition_engine.running:
        return {"success": True, "message": "Already running"}
    cognition_engine.start()
    return {
        "success": True,
        "message": "Autonomous cognition started — Lyra is now thinking for itself",
    }


@router.post("/stop")
async def stop_cognition():
    """Stop the autonomous cognition loop."""
    cognition_engine.stop()
    return {"success": True, "message": "Cognition loop stopped"}


@router.post("/inject")
async def inject_question(req: InjectRequest):
    """Inject a question directly into the cognition queue at high priority."""
    cognition_engine.inject_question(req.question, priority=req.priority)
    return {
        "success": True,
        "message": f"Question injected: {req.question[:80]}",
        "queue_depth": len(cognition_engine.question_queue),
    }


@router.websocket("/stream")
async def cognition_stream(websocket: WebSocket):
    """
    WebSocket live stream of autonomous cognition.
    Sends a JSON event each time a question is answered.
    Clients can watch Lyra think in real time.
    """
    await websocket.accept()
    logger.info("Cognition stream WebSocket connected")

    last_count = cognition_engine.questions_answered

    try:
        while True:
            current_count = cognition_engine.questions_answered

            if current_count > last_count and cognition_engine.recent_entries:
                # New answer — send the latest entry
                entry = cognition_engine.recent_entries[0]
                await websocket.send_json({
                    "type": "cognition",
                    "question": entry.question,
                    "answer": entry.answer,
                    "strategy": entry.strategy,
                    "time": entry.timestamp,
                    "total_answered": current_count,
                    "queue_depth": len(cognition_engine.question_queue),
                })
                last_count = current_count

            # Also send heartbeat with current stats every 5 seconds
            await websocket.send_json({
                "type": "heartbeat",
                "running": cognition_engine.running,
                "questions_answered": cognition_engine.questions_answered,
                "current_question": cognition_engine.current_question[:100],
                "current_strategy": cognition_engine.current_strategy,
                "queue_depth": len(cognition_engine.question_queue),
            })

            await asyncio.sleep(2)

    except WebSocketDisconnect:
        logger.info("Cognition stream WebSocket disconnected")
    except Exception as e:
        logger.error(f"Cognition stream error: {e}")
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
        except Exception:
            pass
