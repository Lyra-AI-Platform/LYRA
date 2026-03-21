"""
Lyra Chat API
WebSocket + REST endpoints for real-time streaming chat.
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from lyra.core.engine import engine
from lyra.core.file_processor import file_processor
from lyra.memory.vector_memory import memory
from lyra.search.web_search import search
from lyra.models.lyra_models import get_model, list_models
from lyra.core.auto_learner import auto_learner

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])

# In-memory conversation store (persists during session)
conversations: Dict[str, List[Dict]] = {}


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    message: str
    model_id: str = "lyra-core"
    llm_model: Optional[str] = None
    use_memory: bool = True
    use_web_search: bool = False
    temperature: float = 0.7
    max_tokens: int = 2048
    stream: bool = True


@router.websocket("/ws/{conversation_id}")
async def chat_websocket(websocket: WebSocket, conversation_id: str):
    """WebSocket endpoint for real-time streaming chat."""
    await websocket.accept()
    logger.info(f"WebSocket connected: {conversation_id}")

    try:
        while True:
            data = await websocket.receive_text()
            request = json.loads(data)

            await handle_chat_ws(websocket, conversation_id, request)

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {conversation_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
        except Exception:
            pass


async def handle_chat_ws(websocket: WebSocket, conv_id: str, request: dict):
    """Handle a single chat message over WebSocket."""
    user_message = request.get("message", "")
    model_id = request.get("model_id", "lyra-core")
    use_memory = request.get("use_memory", True)
    use_web_search = request.get("use_web_search", False)
    temperature = request.get("temperature", 0.7)
    max_tokens = request.get("max_tokens", 2048)

    if not user_message:
        return

    # Get or create conversation
    if conv_id not in conversations:
        conversations[conv_id] = []

    # Feed message to auto-learner (extracts topics for background learning)
    auto_learner.observe_message("user", user_message)

    # Add user message
    conversations[conv_id].append({"role": "user", "content": user_message})

    # Build system prompt
    lyra_model = get_model(model_id)
    system_prompt = lyra_model["system_prompt"]

    # Inject memory context (conversations + learned knowledge)
    memory_context = ""
    if use_memory:
        memory_context = memory.get_context_for_prompt(user_message)
        if memory_context:
            system_prompt += f"\n\n{memory_context}"

        # Also retrieve relevant learned knowledge from web crawls
        learned = memory.retrieve(user_message, n_results=3, memory_type="learned_knowledge")
        if learned:
            lines = ["\n[Lyra LEARNED KNOWLEDGE — from autonomous web research:]"]
            for item in learned:
                snippet = item["content"][:400]
                lines.append(f"• {snippet}")
            system_prompt += "\n" + "\n".join(lines)

        news = memory.retrieve(user_message, n_results=2, memory_type="learned_news")
        if news:
            lines = ["\n[Lyra RECENT NEWS — from RSS feeds:]"]
            for item in news:
                snippet = item["content"][:300]
                lines.append(f"• {snippet}")
            system_prompt += "\n" + "\n".join(lines)

    # Graph knowledge: entity connections and related concepts
    try:
        from lyra.memory.graph_memory import graph_memory
        graph_ctx = graph_memory.get_context_for_prompt(user_message)
        if graph_ctx:
            system_prompt += "\n\n" + graph_ctx
    except Exception:
        pass

    # Web search if requested
    search_context = ""
    if use_web_search or _needs_search(user_message):
        await websocket.send_json({"type": "status", "content": "🔍 Searching the web..."})
        results = await search.search(user_message, max_results=4)
        if results:
            search_context = search.format_for_prompt(results)
            system_prompt += f"\n\n{search_context}"

    # Send thinking indicator
    await websocket.send_json({"type": "start", "model": lyra_model["name"]})

    # Stream response
    full_response = ""
    try:
        async for token in engine.generate(
            messages=conversations[conv_id],
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        ):
            full_response += token
            await websocket.send_json({"type": "token", "content": token})

    except Exception as e:
        await websocket.send_json({"type": "error", "content": f"Generation error: {e}"})
        return

    # Store assistant response
    conversations[conv_id].append({"role": "assistant", "content": full_response})

    # Feed assistant response to auto-learner too
    auto_learner.observe_message("assistant", full_response)

    # Store memory
    if use_memory and full_response:
        # Store interesting facts from conversation
        asyncio.create_task(
            _store_memory_async(user_message, full_response, conv_id)
        )

    # Send completion
    await websocket.send_json({
        "type": "done",
        "conversation_id": conv_id,
        "tokens_used": len(full_response.split()),
    })


async def _store_memory_async(user_msg: str, assistant_msg: str, conv_id: str):
    """Background task to store conversation in memory."""
    try:
        # Store a summary of this exchange
        summary = f"User asked: {user_msg[:200]}\nAssistant responded: {assistant_msg[:300]}"
        memory.store_conversation_summary(summary, conv_id)
    except Exception as e:
        logger.error(f"Memory storage failed: {e}")


def _needs_search(message: str) -> bool:
    """Heuristic: does this message need web search?"""
    search_keywords = [
        "latest", "current", "today", "news", "2024", "2025", "2026",
        "price", "weather", "who won", "what happened", "recent",
        "live", "now", "stock", "search for", "look up", "find me",
    ]
    msg_lower = message.lower()
    return any(kw in msg_lower for kw in search_keywords)


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    conversation_id: str = Form(default=""),
):
    """Upload and process a file for AI analysis."""
    import aiofiles
    from pathlib import Path

    uploads_dir = Path(__file__).parent.parent.parent / "data" / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    # Save file
    file_id = str(uuid.uuid4())[:8]
    safe_name = f"{file_id}_{file.filename}"
    dest = uploads_dir / safe_name

    async with aiofiles.open(dest, "wb") as f:
        content = await file.read()
        await f.write(content)

    # Process
    result = await file_processor.process(str(dest), file.filename)

    if not result["success"]:
        return {"success": False, "error": result["error"]}

    # Add to conversation context if conversation_id provided
    if conversation_id and result["content"]:
        if conversation_id not in conversations:
            conversations[conversation_id] = []

        file_context = file_processor.format_for_prompt(result)
        conversations[conversation_id].append({
            "role": "user",
            "content": file_context,
        })

    return {
        "success": True,
        "filename": file.filename,
        "type": result["type"],
        "size": result["size_human"],
        "content_preview": result["content"][:200] if result["content"] else "",
        "file_id": file_id,
    }


@router.get("/conversations")
async def get_conversations():
    """List all active conversations."""
    result = []
    for conv_id, messages in conversations.items():
        if messages:
            first_user = next((m["content"] for m in messages if m["role"] == "user"), "")
            result.append({
                "id": conv_id,
                "title": first_user[:60] + "..." if len(first_user) > 60 else first_user,
                "message_count": len(messages),
                "created": conv_id[:8],  # conv_id starts with timestamp
            })
    return {"conversations": result}


@router.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    """Get full conversation history."""
    if conv_id not in conversations:
        return {"messages": []}
    return {"messages": conversations[conv_id]}


@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    """Delete a conversation."""
    conversations.pop(conv_id, None)
    return {"success": True}


@router.post("/conversations/new")
async def new_conversation():
    """Create a new conversation ID."""
    conv_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    conversations[conv_id] = []
    return {"conversation_id": conv_id}
