"""One way to call any model for Lyra Labs.

  lyra       Lyra's own model, running locally on the server through Ollama (ollama_backend.py)
  anthropic  Claude, with the user's own API key (official SDK)
  openai     any OpenAI-compatible endpoint (OpenAI, Mistral, Groq, Together, OpenRouter,
             a self-hosted vLLM...) with the user's key

People's keys are encrypted before they are stored (Fernet, keyed from the server secret) and
are only ever decrypted to make a call. A user-supplied endpoint must be public HTTPS: Lyra
refuses to call addresses on its own machine or private networks, so nobody can point it at
the NAS's internal services (server-side request forgery).
"""
import base64
import hashlib
import ipaddress
import socket
from typing import Dict, List, Optional
from urllib.parse import urlsplit

import httpx

from lyra.api.users_api import SECRET_KEY

MAX_OUTPUT = 4000
LYRA_MAX_OUTPUT = 900          # the local model runs on a CPU: keep answers short
DEFAULT_CLAUDE = "claude-opus-5-5"


class LLMError(Exception):
    """A message that can be shown to the user as is."""


# ── Keys at rest ────────────────────────────────────────────────────────────

def _fernet():
    from cryptography.fernet import Fernet
    key = base64.urlsafe_b64encode(hashlib.sha256(("lyra-labs-keys:" + SECRET_KEY).encode()).digest())
    return Fernet(key)


def seal(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode() if secret else ""


def unseal(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode() if token else ""


def hint(secret: str) -> str:
    return f"…{secret[-4:]}" if len(secret) >= 8 else "set"


# ── Endpoint safety ─────────────────────────────────────────────────────────

def check_endpoint(url: str) -> str:
    """The base URL if it is public HTTPS, else LLMError."""
    parts = urlsplit((url or "").strip())
    if parts.scheme != "https" or not parts.hostname:
        raise LLMError("The endpoint must start with https://")
    if parts.username or parts.password:
        raise LLMError("Put the key in the key field, not in the address")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise LLMError("That address doesn't resolve")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise LLMError("Lyra won't call private or local network addresses. To use a model on your own "
                           "computer, choose “On this device” instead: it runs in your browser.")
    return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"


# ── Calls ───────────────────────────────────────────────────────────────────

async def _lyra(system: str, messages: List[Dict], max_tokens: int) -> str:
    from lyra.core import ollama_backend
    if not ollama_backend.enabled():
        raise LLMError("Lyra's own model isn't switched on on this server yet. Connect your own AI for now.")
    out = []
    try:
        async for piece in ollama_backend.stream(messages, system, max_tokens=min(max_tokens, LYRA_MAX_OUTPUT)):
            out.append(piece)
    except ollama_backend.Unavailable:
        raise LLMError("Lyra's own model is busy or restarting. Try again in a minute.")
    return "".join(out).strip()


async def _anthropic(conn: Dict, system: str, messages: List[Dict], max_tokens: int) -> str:
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=unseal(conn["key"]), timeout=120.0, max_retries=1)
    model = conn.get("model") or DEFAULT_CLAUDE
    try:
        # A refused request is retried on a fallback model chosen by the API ("default").
        response = await client.beta.messages.create(
            model=model, max_tokens=min(max_tokens, MAX_OUTPUT), system=system, messages=messages,
            betas=["server-side-fallback-2026-07-01"], extra_body={"fallbacks": "default"})
    except anthropic.AuthenticationError:
        raise LLMError("Anthropic rejected the API key. Check it in Lyra Labs → Your AI.")
    except anthropic.PermissionDeniedError:
        raise LLMError("That Anthropic key can't use this model.")
    except anthropic.NotFoundError:
        raise LLMError(f"Anthropic doesn't know the model “{model}”.")
    except anthropic.RateLimitError:
        raise LLMError("Your Anthropic account is rate-limited right now. Try again shortly.")
    except anthropic.BadRequestError as e:
        raise LLMError(f"Anthropic refused the request: {e.message}"[:300])
    except anthropic.APIStatusError as e:
        raise LLMError(f"Anthropic had a problem ({e.status_code}). Try again shortly.")
    except anthropic.APIConnectionError:
        raise LLMError("Couldn't reach Anthropic.")
    if response.stop_reason == "refusal":
        raise LLMError("Claude declined this request.")
    return "".join(b.text for b in response.content if b.type == "text").strip()


async def _openai(conn: Dict, system: str, messages: List[Dict], max_tokens: int) -> str:
    base = check_endpoint(conn.get("base_url") or "https://api.openai.com/v1")
    body = {"model": conn.get("model") or "gpt-4o-mini", "max_tokens": min(max_tokens, MAX_OUTPUT),
            "messages": [{"role": "system", "content": system}] + messages}
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
            r = await client.post(f"{base}/chat/completions", json=body,
                                  headers={"Authorization": f"Bearer {unseal(conn['key'])}"})
    except httpx.HTTPError:
        raise LLMError("Couldn't reach your AI's endpoint.")
    if r.status_code in (401, 403):
        raise LLMError("Your AI's endpoint rejected the key.")
    if r.status_code == 429:
        raise LLMError("Your AI's endpoint is rate-limiting. Try again shortly.")
    if r.status_code >= 400:
        raise LLMError(f"Your AI's endpoint answered {r.status_code}.")
    try:
        return (r.json()["choices"][0]["message"]["content"] or "").strip()
    except (ValueError, KeyError, IndexError, TypeError):
        raise LLMError("Your AI's endpoint answered in an unexpected format (it must be OpenAI-compatible).")


async def complete(conn: Optional[Dict], system: str, messages: List[Dict], max_tokens: int = 1500) -> str:
    """conn None = Lyra's own model; else a stored connection {kind, base_url, model, key}."""
    if not conn:
        return await _lyra(system, messages, max_tokens)
    if conn["kind"] == "anthropic":
        return await _anthropic(conn, system, messages, max_tokens)
    if conn["kind"] == "openai":
        return await _openai(conn, system, messages, max_tokens)
    raise LLMError("Unknown kind of connection")
