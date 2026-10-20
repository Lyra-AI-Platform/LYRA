"""Local model through Ollama (lyra/core/ollama_backend.py): prompts trimmed to what a small
CPU model can read quickly, and a clean Unavailable when Ollama isn't there."""
import asyncio

import pytest

from lyra.core import ollama_backend as ob


def test_off_unless_a_model_is_named(monkeypatch):
    monkeypatch.delenv("LYRA_OLLAMA_MODEL", raising=False)
    assert not ob.enabled()
    monkeypatch.setenv("LYRA_OLLAMA_MODEL", "qwen3:4b-instruct")
    assert ob.enabled() and ob.model() == "qwen3:4b-instruct"


def test_prompt_is_trimmed():
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(30)]
    history.insert(5, {"role": "system", "content": "stray"})
    msgs = ob.prompt_for(history, "x" * 20000)
    assert msgs[0]["role"] == "system" and len(msgs[0]["content"]) < ob.SYSTEM_CHARS + 10
    assert len(msgs) == 1 + ob.HISTORY_TURNS
    assert msgs[-1]["content"] == "m29"
    assert all(m["role"] in ("user", "assistant") for m in msgs[1:])


def test_unreachable_ollama_raises_unavailable(monkeypatch):
    monkeypatch.setenv("LYRA_OLLAMA_MODEL", "qwen3:4b-instruct")
    monkeypatch.setenv("LYRA_OLLAMA_URL", "http://127.0.0.1:9")   # nothing listens on the discard port

    async def run():
        return [p async for p in ob.stream([{"role": "user", "content": "hi"}], "be brief")]
    with pytest.raises(ob.Unavailable):
        asyncio.run(run())
