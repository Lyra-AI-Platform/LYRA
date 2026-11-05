"""Chat through a local Ollama server (https://ollama.com), when LYRA_OLLAMA_MODEL is set.

Ollama runs the model in its own process and keeps it loaded between messages, so Lyra
stays light. On the NAS (4 cores, 7.7 GB, no GPU) the model is qwen3:4b-instruct; see
deploy/install-llm.sh.

  LYRA_OLLAMA_MODEL   model tag, e.g. qwen3:4b-instruct (unset: Ollama isn't used)
  LYRA_OLLAMA_URL     default http://127.0.0.1:11434
  LYRA_OLLAMA_CTX     context window in tokens, default 4096
  LYRA_OLLAMA_THREADS CPU threads for the model, default every core

A small model on a CPU reads long prompts slowly, so the prompt is trimmed to fit and laid out
so Ollama can reuse what it has already read (prompt_for, lyra/core/chat_speed.py).
"""
import json
import os
from typing import AsyncIterator, Dict, List

import httpx

from lyra.core import chat_speed

SYSTEM_CHARS = 2400       # about 600 tokens of the model's own instructions
HISTORY_TURNS = 8         # the last eight messages of the conversation
MAX_REPLY = 1024


class Unavailable(Exception):
    """Ollama isn't running or doesn't have the model; the caller falls back."""


def model() -> str:
    return os.getenv("LYRA_OLLAMA_MODEL", "").strip()


def enabled() -> bool:
    return bool(model())


def _url() -> str:
    return os.getenv("LYRA_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")


def prompt_for(messages: List[Dict], system_prompt: str, context: str = "") -> List[Dict]:
    system = system_prompt if len(system_prompt) <= SYSTEM_CHARS else system_prompt[:SYSTEM_CHARS] + "\n[…]"
    turns = [{"role": m["role"], "content": m["content"]} for m in messages[-HISTORY_TURNS:]
             if m.get("role") in ("user", "assistant")]
    return [{"role": "system", "content": system}] + chat_speed.with_context(turns, context)


def _options(max_tokens: int, temperature: float) -> Dict:
    return {"num_ctx": int(os.getenv("LYRA_OLLAMA_CTX", "4096")),
            "num_thread": int(os.getenv("LYRA_OLLAMA_THREADS") or os.cpu_count() or 4),
            "num_predict": min(int(max_tokens or MAX_REPLY), MAX_REPLY),
            "temperature": float(temperature)}


async def warm() -> None:
    """Load the model when Lyra starts, so the first visitor doesn't wait for the disk."""
    if not enabled():
        return
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=3.0)) as client:
            await client.post(f"{_url()}/api/chat", json={"model": model(), "messages": [], "keep_alive": "24h"})
    except httpx.HTTPError:
        pass   # chat reports it properly when someone actually asks


async def stream(messages: List[Dict], system_prompt: str, max_tokens: int = MAX_REPLY,
                 temperature: float = 0.7, context: str = "") -> AsyncIterator[str]:
    """Yield the reply a piece at a time. Raises Unavailable before the first piece if Ollama
    can't answer, so nothing half-written reaches the user."""
    body = {
        "model": model(),
        "messages": prompt_for(messages, system_prompt, context),
        "stream": True,
        "keep_alive": "24h",
        "options": _options(max_tokens, temperature),
    }
    timeout = httpx.Timeout(connect=3.0, read=180.0, write=10.0, pool=5.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", f"{_url()}/api/chat", json=body) as r:
                if r.status_code != 200:
                    raise Unavailable(f"Ollama answered {r.status_code}: {(await r.aread())[:200]!r}")
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise Unavailable(chunk["error"])
                    piece = (chunk.get("message") or {}).get("content", "")
                    if piece:
                        yield piece
                    if chunk.get("done"):
                        return
    except httpx.HTTPError as e:
        raise Unavailable(str(e)) from e
