"""Keeping the first word of a reply quick on a small server.

A CPU model spends most of its time reading the prompt, and Ollama only re-reads what changed
since the last message. So the part that stays the same (instructions, then the conversation)
goes first, and what's looked up for this one message goes last, on the newest question. A
follow-up then reads only that, not the whole conversation again.
"""
import re
from typing import Dict, List

CONTEXT_CHARS = 2400         # looked-up context on a small local model, about 600 tokens
LOOKUP_SECONDS = 1.5         # past this, answer with what's been found rather than keep looking
SEARCH_SECONDS = 6.0

_QUICK = re.compile(r"^(hi|hey|hello|yo|thanks|thank you|ok|okay|cool|great|nice|yes|no|sure|bye|lol|good (morning|afternoon|evening|night))\b", re.I)


def is_quick(message: str) -> bool:
    """A greeting or a one-word reply needs no looking up."""
    text = (message or "").strip()
    return len(text.split()) <= 5 and len(text) <= 40 and bool(_QUICK.match(text)) and "?" not in text


def looked_up(system_prompt: str, base_prompt: str) -> str:
    """What was added to the model's own instructions for this one message."""
    return system_prompt[len(base_prompt):].strip() if system_prompt.startswith(base_prompt) else ""


def with_context(turns: List[Dict], context: str, limit: int = CONTEXT_CHARS) -> List[Dict]:
    """Put this message's context on the newest question, leaving earlier turns untouched."""
    if not context or not turns or turns[-1]["role"] != "user":
        return turns
    text = context if len(context) <= limit else context[:limit] + "\n[…]"
    return turns[:-1] + [{"role": "user", "content": f"Background for this question:\n{text}\n\nQuestion: {turns[-1]['content']}"}]
