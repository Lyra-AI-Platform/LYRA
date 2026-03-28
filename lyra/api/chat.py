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
from lyra.core.reasoning_engine import reasoning_engine
from lyra.core.reflection import reflector
from lyra.core.self_awareness import self_awareness
from lyra.core.quantum_sim import quantum_sim

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

    # ── Signal user priority — background cognition immediately yields ──
    engine.set_user_active()

    # Feed message to auto-learner (fast regex scoring, LLM extraction queued async)
    auto_learner.observe_message("user", user_message)

    # Also inject self-conversation insights relevant to this topic into memory context
    try:
        self_convos = memory.retrieve(user_message, n_results=2, memory_type="self_conversation")
        # Will be included naturally via memory.get_context_for_prompt below
    except Exception:
        pass

    # Add user message
    conversations[conv_id].append({"role": "user", "content": user_message})

    # Build system prompt
    lyra_model = get_model(model_id)
    system_prompt = lyra_model["system_prompt"]

    # ── Reasoning Engine: classify complexity and build enhanced context ──
    reasoning_result = await reasoning_engine.build_enhanced_context(user_message)
    complexity = reasoning_result.complexity

    if complexity != "simple":
        await websocket.send_json({
            "type": "status",
            "content": f"🧠 Reasoning ({complexity})..."
        })

    # ── Memory context injection ──
    if use_memory:
        # Core memory context (importance-ranked: wisdom > templates > user facts > knowledge)
        memory_context = memory.get_context_for_prompt(user_message)
        if memory_context:
            system_prompt += f"\n\n{memory_context}"

        # Reasoning engine's enhanced context (sub-question research + synthesized wisdom)
        if reasoning_result.enhanced_context:
            system_prompt += f"\n\n{reasoning_result.enhanced_context}"

        # Synthesized wisdom (direct fetch if not already in reasoning context)
        if complexity == "simple":
            wisdom = memory.retrieve(user_message, n_results=2, memory_type="synthesized_wisdom")
            if wisdom:
                lines = ["\n[SYNTHESIZED KNOWLEDGE:]"]
                for item in wisdom[:2]:
                    lines.append(f"★ {item['content'][:350]}")
                system_prompt += "\n" + "\n".join(lines)

        # Reasoning templates: proven high-quality reasoning patterns
        template_ctx = await reflector.get_template_context(user_message)
        if template_ctx:
            system_prompt += template_ctx

        # Learned knowledge from web crawls
        learned = memory.retrieve(user_message, n_results=3, memory_type="learned_knowledge")
        if learned:
            lines = ["\n[Lyra LEARNED KNOWLEDGE — from autonomous web research:]"]
            for item in learned:
                snippet = item["content"][:400]
                lines.append(f"• {snippet}")
            system_prompt += "\n" + "\n".join(lines)

        # Recent news
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

    # Self-awareness: inject Lyra's current self-model into context
    try:
        self_desc = self_awareness.get_self_description()
        if self_desc:
            system_prompt += f"\n\n{self_desc}"
    except Exception:
        pass

    # Quantum context: if question involves quantum topics, note simulation availability
    _quantum_keywords = [
        "quantum", "qubit", "superposition", "entanglement", "bell state",
        "grover", "shor", "qft", "teleportation", "vqe", "circuit",
    ]
    if any(kw in user_message.lower() for kw in _quantum_keywords):
        system_prompt += (
            "\n\n[QUANTUM CAPABILITY] You have access to a full quantum circuit simulator. "
            f"You have run {quantum_sim.experiments_run} quantum experiments. "
            "You can simulate Bell states, GHZ states, QFT, Grover search, teleportation, and VQE."
        )

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

    # ── Language Backbone fallback when no LLM model is loaded ──
    if not engine.loaded_model_name:
        try:
            from lyra.core.language_backbone import language_backbone
            if not language_backbone._initialized:
                await language_backbone.initialize()
            # Use language backbone for word-level understanding + answer
            understanding = language_backbone.understand(user_message)
            memory_ctx = memory.get_context_for_prompt(user_message) if use_memory else ""
            backbone_answer = language_backbone.answer(user_message, memory_ctx)
            # Annotate with understanding
            entities = understanding.get("entities", [])
            keywords = understanding.get("keywords", [])[:5]
            full_response = backbone_answer
            if keywords:
                full_response += f"\n\n*[Detected keywords: {', '.join(keywords)}]*"
            if entities:
                full_response += f"\n*[Entities: {', '.join(f'{e[0]} ({e[1]})' for e in entities[:3])}]*"
            full_response += (
                "\n\n*Note: Running in Language Backbone mode (no LLM loaded). "
                "Load a model for full conversational AI. "
                "Word knowledge from WordNet (117,659 concepts) + spaCy NLP.*"
            )
            # Emit as a stream of tokens
            for word in full_response.split():
                await websocket.send_json({"type": "token", "content": word + " "})
            # Feed to language backbone learning
            language_backbone.read_and_learn(user_message)
        except Exception as e:
            full_response = f"No model loaded. Language backbone error: {e}"
            await websocket.send_json({"type": "token", "content": full_response})
    else:
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
            engine.set_user_idle()  # Always release priority on error
            await websocket.send_json({"type": "error", "content": f"Generation error: {e}"})
            return

    # Store assistant response
    conversations[conv_id].append({"role": "assistant", "content": full_response})

    # Feed complete exchange to auto-learner (captures knowledge gaps from AI response)
    auto_learner.observe_exchange(user_message, full_response)

    # Store memory
    if use_memory and full_response:
        asyncio.create_task(
            _store_memory_async(user_message, full_response, conv_id)
        )

    # Self-reflection: evaluate quality and store high-quality patterns as templates
    # Runs async in background — never delays the user response
    asyncio.create_task(
        reflector.evaluate_async(user_message, full_response, conv_id)
    )

    # Update self-awareness: record conversation use
    try:
        self_awareness.observe_capability_use("conversation", success=True)
        self_awareness.observe_capability_use("reasoning", success=len(full_response) > 100)
    except Exception:
        pass

    # ── Release user priority — background cognition may resume ──
    engine.set_user_idle()

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
