"""Small finance-specific sentiment lexicon (in the spirit of Loughran-McDonald).
No model download needed; good enough to tell a downgrade from a beat."""
import re

POSITIVE = {
    "beat", "beats", "surge", "surges", "soar", "soars", "rally", "rallies", "record", "upgrade",
    "upgraded", "outperform", "bullish", "growth", "profit", "profitable", "gain", "gains", "jump",
    "jumps", "strong", "stronger", "raise", "raises", "raised", "boost", "boosts", "buyback",
    "dividend", "approval", "approved", "partnership", "breakthrough", "expands", "expansion",
    "exceeds", "exceeded", "optimistic", "momentum", "rebound", "rebounds", "upside", "win", "wins",
    "contract", "acquire", "innovative", "demand", "accelerate", "accelerates", "buy",
}
NEGATIVE = {
    "miss", "misses", "missed", "plunge", "plunges", "crash", "crashes", "slump", "slumps", "fall",
    "falls", "drop", "drops", "downgrade", "downgraded", "underperform", "bearish", "loss", "losses",
    "weak", "weaker", "cut", "cuts", "lawsuit", "sued", "probe", "investigation", "fraud", "recall",
    "bankruptcy", "default", "layoffs", "layoff", "warning", "warns", "decline", "declines", "risk",
    "risks", "volatile", "selloff", "sell-off", "fine", "fined", "halt", "halted", "delay", "delays",
    "downside", "concern", "concerns", "subpoena", "short", "tumble", "tumbles", "sink", "sinks", "sell",
}
NEGATORS = {"not", "no", "never", "without", "fails", "failed"}
_WORD = re.compile(r"[a-z][a-z\-']+")


def score(text: str) -> float:
    """Sentiment in [-1, 1]. 0 means neutral or no signal."""
    words = _WORD.findall((text or "").lower())
    pos = neg = 0
    for i, w in enumerate(words):
        flip = i > 0 and words[i - 1] in NEGATORS
        if w in POSITIVE:
            neg, pos = (neg + 1, pos) if flip else (neg, pos + 1)
        elif w in NEGATIVE:
            pos, neg = (pos + 1, neg) if flip else (pos, neg + 1)
    total = pos + neg
    return 0.0 if total == 0 else (pos - neg) / (total + 2)
