"""
LyraAuth — Human Intelligence Authenticator
Copyright (C) 2026 Lyra Contributors

Modern CAPTCHA replacement that:
  1. Proves the user is human (website security)
  2. Collects high-quality labeled data to train Lyra's own language model
  3. Is fun — not "click all traffic lights" but genuinely interesting challenges

Challenge types (10 varieties):
  WORD_COMPLETE    — "The sky is ___" (natural language patterns)
  ANALOGY          — "Hot is to Cold as Fast is to ___" (reasoning)
  SENTIMENT        — "Does this sentence feel positive or negative?" (RLHF signal)
  COMMON_SENSE     — "Can a rock float?" Yes/No (world knowledge)
  RANKING          — "Rank these responses best to worst" (preference data)
  CREATIVE_TAG     — "Describe this pattern in 3 words" (vocabulary + creativity)
  FACT_CHECK       — "Is this plausible? [statement]" (factual grounding)
  SEQUENCE         — "What comes next: 2, 4, 8, ___?" (reasoning)
  BETTER_WORD      — "Replace the underlined word with a more precise one" (language quality)
  EMOJI_MEANING    — "What emotion does 🌊💭🌙 suggest?" (semantic mapping)

Each solved challenge = one labeled training example for Lyra.
100 users = 100 training examples per challenge served.
1,000 websites × 1,000 daily users = 1,000,000 training examples/day.
"""
import asyncio
import hashlib
import json
import logging
import random
import secrets
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "auth"
DATA_DIR.mkdir(parents=True, exist_ok=True)
TRAINING_DIR = DATA_DIR / "training_data"
TRAINING_DIR.mkdir(parents=True, exist_ok=True)


class ChallengeType(str, Enum):
    WORD_COMPLETE  = "word_complete"
    ANALOGY        = "analogy"
    SENTIMENT      = "sentiment"
    COMMON_SENSE   = "common_sense"
    RANKING        = "ranking"
    CREATIVE_TAG   = "creative_tag"
    FACT_CHECK     = "fact_check"
    SEQUENCE       = "sequence"
    BETTER_WORD    = "better_word"
    EMOJI_MEANING  = "emoji_meaning"


@dataclass
class Challenge:
    id: str
    type: ChallengeType
    prompt: str
    options: List[str]           # [] for free-text, list for multiple choice
    correct_answer: Optional[str]  # None for subjective challenges
    display_data: Dict            # extra data for rendering (images, etc.)
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    training_value: float = 1.0  # how valuable this is as training data (0-2)


@dataclass
class ChallengeResponse:
    challenge_id: str
    session_id: str
    answer: str
    answer_time_ms: int          # how long user took — too fast = bot
    site_key: str
    user_agent: str = ""
    timestamp: float = field(default_factory=time.time)
    is_human: bool = False
    confidence: float = 0.0
    training_label: Optional[str] = None


# ── Challenge Library ─────────────────────────────────────────────────────────

WORD_COMPLETE_CHALLENGES = [
    ("The sun rises in the ___", ["east", "west", "north", "morning"], "east"),
    ("You use a ___ to open a lock", ["key", "hammer", "spoon", "phone"], "key"),
    ("Water boils at ___ degrees Celsius", ["100", "0", "50", "200"], "100"),
    ("A baby dog is called a ___", ["puppy", "kitten", "cub", "foal"], "puppy"),
    ("The opposite of silence is ___", ["noise", "quiet", "empty", "slow"], "noise"),
    ("Books are kept in a ___", ["library", "hospital", "stadium", "kitchen"], "library"),
    ("You sleep in a ___", ["bed", "chair", "roof", "window"], "bed"),
    ("Ice is ___ water", ["frozen", "boiling", "colored", "liquid"], "frozen"),
    ("A ___ is used to cut bread", ["knife", "spoon", "fork", "pen"], "knife"),
    ("The moon appears at ___", ["night", "noon", "dawn", "noon"], "night"),
    ("Fish live in ___", ["water", "trees", "soil", "air"], "water"),
    ("We read with our ___", ["eyes", "hands", "ears", "feet"], "eyes"),
]

ANALOGY_CHALLENGES = [
    ("Bird is to sky as fish is to ___", ["water", "land", "air", "fire"], "water"),
    ("Doctor is to hospital as teacher is to ___", ["school", "market", "park", "airport"], "school"),
    ("Hot is to cold as fast is to ___", ["slow", "warm", "quick", "high"], "slow"),
    ("Sun is to day as moon is to ___", ["night", "morning", "noon", "evening"], "night"),
    ("Pen is to write as knife is to ___", ["cut", "eat", "sing", "jump"], "cut"),
    ("Eye is to see as ear is to ___", ["hear", "touch", "smell", "taste"], "hear"),
    ("Cat is to meow as dog is to ___", ["bark", "moo", "tweet", "roar"], "bark"),
    ("Painter is to brush as writer is to ___", ["pen", "hammer", "ruler", "scissors"], "pen"),
    ("Summer is to hot as winter is to ___", ["cold", "rainy", "sunny", "windy"], "cold"),
    ("Big is to small as tall is to ___", ["short", "wide", "fat", "thin"], "short"),
]

SENTIMENT_CHALLENGES = [
    ("I finally finished a book I loved!", None),
    ("The traffic was awful and I missed my flight.", None),
    ("My dog learned a new trick today.", None),
    ("The meeting dragged on for three hours with no conclusion.", None),
    ("Unexpected kindness from a stranger made my day.", None),
    ("My phone died right when I needed it most.", None),
    ("I got to sleep in on a rainy Sunday morning.", None),
    ("The restaurant was noisy and the food was cold.", None),
    ("She smiled when she saw the surprise party.", None),
    ("I've been stuck in traffic for two hours with no end in sight.", None),
]

COMMON_SENSE_CHALLENGES = [
    ("Can you fold water?", False),
    ("Does a shadow have weight?", False),
    ("Can a cat climb a tree?", True),
    ("Does fire burn things?", True),
    ("Can you hear light?", False),
    ("Do plants need sunlight to grow?", True),
    ("Can a fish survive out of water for a week?", False),
    ("Does the earth spin?", True),
    ("Can you sneeze with your eyes open?", False),
    ("Does ice melt when heated?", True),
    ("Can you read in the dark without a light?", False),
    ("Does music require sound?", True),
]

SEQUENCE_CHALLENGES = [
    ("1, 2, 4, 8, ___", ["16", "12", "10", "32"], "16"),
    ("A, C, E, G, ___", ["I", "H", "J", "K"], "I"),
    ("1, 1, 2, 3, 5, ___", ["8", "6", "7", "9"], "8"),
    ("Monday, Wednesday, Friday, ___", ["Sunday", "Tuesday", "Saturday", "Thursday"], "Sunday"),
    ("10, 20, 30, 40, ___", ["50", "45", "35", "55"], "50"),
    ("Spring, Summer, Autumn, ___", ["Winter", "Fall", "Rain", "Snow"], "Winter"),
    ("2, 4, 6, 8, ___", ["10", "9", "12", "7"], "10"),
    ("Red, Orange, Yellow, ___", ["Green", "Purple", "Blue", "Black"], "Green"),
]

BETTER_WORD_CHALLENGES = [
    ("The movie was **good**.", ["excellent", "nice", "okay", "fine"], None),
    ("She walked **fast** to the exit.", ["sprinted", "moved", "ran", "went"], None),
    ("The food tasted **bad**.", ["awful", "poor", "not nice", "wrong"], None),
    ("He is a **smart** person.", ["brilliant", "okay", "clever", "smart-ish"], None),
    ("The problem was **hard** to solve.", ["complex", "difficult", "tough", "tricky"], None),
    ("It was a **big** building.", ["massive", "large", "huge", "giant"], None),
    ("The child was **happy**.", ["overjoyed", "content", "glad", "pleased"], None),
    ("She spoke in a **quiet** voice.", ["hushed", "soft", "low", "tiny"], None),
]

EMOJI_MEANING_CHALLENGES = [
    ("🌊💭🌙", None),
    ("🔥💪⚡", None),
    ("🌱🌿🍀", None),
    ("😴💤🌙", None),
    ("🎵🎶❤️", None),
    ("⚡🔬🔭", None),
    ("🏆🥇👑", None),
    ("🌍💚♻️", None),
    ("📚🖊️🎓", None),
    ("🌅🐦🍃", None),
]

FACT_CHECK_CHALLENGES = [
    ("The Great Wall of China is visible from space with the naked eye.", False, "This is a common myth — it's too narrow to see from space."),
    ("Humans use only 10% of their brain.", False, "We use virtually all of our brain, just not all at once."),
    ("Lightning can strike the same place twice.", True, "Lightning frequently strikes the same place, especially tall structures."),
    ("Goldfish have a 3-second memory.", False, "Goldfish can remember things for months."),
    ("Hot water can freeze faster than cold water under some conditions.", True, "This is called the Mpemba effect."),
    ("Bats are blind.", False, "All bat species have eyes and can see."),
    ("A group of crows is called a murder.", True, "The collective noun for crows is indeed 'a murder'."),
    ("The tongue has specific zones for different tastes.", False, "Taste receptors for all tastes are distributed across the whole tongue."),
]


class ChallengeEngine:
    """
    Generates, serves, and verifies human authentication challenges.
    Each solved challenge produces a training data record.
    """

    def __init__(self):
        self._active: Dict[str, Challenge] = {}   # id → challenge
        self._sessions: Dict[str, dict] = {}       # session_id → state
        self._site_keys: Dict[str, dict] = {}      # site_key → site info
        self.challenges_served = 0
        self.challenges_passed = 0
        self.training_records = 0
        self._cleanup_task: Optional[asyncio.Task] = None

    def start(self):
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    def stop(self):
        if self._cleanup_task:
            self._cleanup_task.cancel()

    async def _cleanup_loop(self):
        while True:
            await asyncio.sleep(300)
            now = time.time()
            expired = [k for k, c in self._active.items() if c.expires_at < now]
            for k in expired:
                del self._active[k]

    def register_site(self, domain: str, contact_email: str) -> Dict:
        """Register a website to use LyraAuth."""
        site_key = "lyra_" + secrets.token_hex(16)
        secret_key = "lyrasecret_" + secrets.token_hex(24)
        self._site_keys[site_key] = {
            "domain": domain,
            "contact_email": contact_email,
            "site_key": site_key,
            "secret_key": secret_key,
            "registered_at": time.time(),
            "challenges_served": 0,
            "humans_verified": 0,
        }
        return {"site_key": site_key, "secret_key": secret_key}

    def generate_challenge(self, difficulty: str = "normal") -> Challenge:
        """Generate a fresh challenge from random type."""
        ctype = random.choice(list(ChallengeType))
        return self._build_challenge(ctype, difficulty)

    def _build_challenge(self, ctype: ChallengeType, difficulty: str) -> Challenge:
        cid = str(uuid.uuid4())[:12]
        now = time.time()

        if ctype == ChallengeType.WORD_COMPLETE:
            prompt, options, answer = random.choice(WORD_COMPLETE_CHALLENGES)
            c = Challenge(id=cid, type=ctype, prompt=prompt, options=options,
                          correct_answer=answer, display_data={}, training_value=1.2)

        elif ctype == ChallengeType.ANALOGY:
            prompt, options, answer = random.choice(ANALOGY_CHALLENGES)
            c = Challenge(id=cid, type=ctype, prompt=prompt, options=options,
                          correct_answer=answer, display_data={}, training_value=1.5)

        elif ctype == ChallengeType.SENTIMENT:
            prompt, _ = random.choice(SENTIMENT_CHALLENGES)
            c = Challenge(id=cid, type=ctype,
                          prompt=f"Does this feel positive or negative?\n\n\"{prompt}\"",
                          options=["Positive 😊", "Negative 😔", "Neutral 😐"],
                          correct_answer=None,
                          display_data={"original_text": prompt},
                          training_value=1.8)

        elif ctype == ChallengeType.COMMON_SENSE:
            prompt, answer, *_ = random.choice(COMMON_SENSE_CHALLENGES)
            c = Challenge(id=cid, type=ctype,
                          prompt=f"True or False: {prompt}",
                          options=["True ✓", "False ✗"],
                          correct_answer="True ✓" if answer else "False ✗",
                          display_data={}, training_value=1.3)

        elif ctype == ChallengeType.SEQUENCE:
            prompt, options, answer = random.choice(SEQUENCE_CHALLENGES)
            c = Challenge(id=cid, type=ctype,
                          prompt=f"What comes next?\n{prompt}",
                          options=options, correct_answer=answer,
                          display_data={}, training_value=1.4)

        elif ctype == ChallengeType.BETTER_WORD:
            sentence, options, _ = random.choice(BETTER_WORD_CHALLENGES)
            c = Challenge(id=cid, type=ctype,
                          prompt=f"Choose the most precise replacement for the bold word:\n\n{sentence}",
                          options=options, correct_answer=None,
                          display_data={"sentence": sentence}, training_value=1.6)

        elif ctype == ChallengeType.EMOJI_MEANING:
            emoji, _ = random.choice(EMOJI_MEANING_CHALLENGES)
            c = Challenge(id=cid, type=ctype,
                          prompt=f"In 2-4 words, what mood or idea do these emojis suggest?\n\n{emoji}",
                          options=[],  # free text
                          correct_answer=None,
                          display_data={"emoji": emoji}, training_value=2.0)

        elif ctype == ChallengeType.FACT_CHECK:
            statement, answer, explanation = random.choice(FACT_CHECK_CHALLENGES)
            c = Challenge(id=cid, type=ctype,
                          prompt=f"Is this statement plausible?\n\n\"{statement}\"",
                          options=["Yes, plausible ✓", "No, this seems wrong ✗"],
                          correct_answer="Yes, plausible ✓" if answer else "No, this seems wrong ✗",
                          display_data={"explanation": explanation}, training_value=1.5)

        else:
            # Fallback to word complete
            prompt, options, answer = random.choice(WORD_COMPLETE_CHALLENGES)
            c = Challenge(id=cid, type=ctype, prompt=prompt, options=options,
                          correct_answer=answer, display_data={}, training_value=1.0)

        c.expires_at = now + 300  # 5 minute expiry
        self._active[cid] = c
        self.challenges_served += 1
        return c

    def verify_response(self, resp: ChallengeResponse) -> Tuple[bool, float, str]:
        """
        Verify a challenge response.
        Returns: (is_human, confidence, token)
        """
        challenge = self._active.get(resp.challenge_id)
        if not challenge:
            return False, 0.0, ""

        if time.time() > challenge.expires_at:
            return False, 0.0, ""

        # Bot detection heuristics
        if resp.answer_time_ms < 400:   # Too fast — bots answer instantly
            return False, 0.0, ""
        if resp.answer_time_ms > 120_000:  # 2 minutes — probably abandoned
            return False, 0.1, ""

        # Score the answer
        confidence = 0.5  # base
        is_correct = True

        if challenge.correct_answer is not None:
            is_correct = resp.answer.strip() == challenge.correct_answer.strip()
            confidence = 0.95 if is_correct else 0.1
        else:
            # Subjective challenge — any non-empty answer from a human is valid
            if resp.answer.strip():
                confidence = 0.85
                is_correct = True

        # Time-based confidence boost (human-typical response 1-30s)
        if 1000 < resp.answer_time_ms < 30_000:
            confidence = min(1.0, confidence + 0.05)

        is_human = confidence > 0.6

        if is_human:
            # Record as training data
            self._store_training_record(challenge, resp, confidence)
            self.challenges_passed += 1
            token = self._mint_token(resp.site_key, resp.session_id, confidence)
            return True, confidence, token

        return False, confidence, ""

    def _store_training_record(self, challenge: Challenge, resp: ChallengeResponse, conf: float):
        """Convert solved challenge into a training data record."""
        record = {
            "id": str(uuid.uuid4()),
            "type": challenge.type,
            "prompt": challenge.prompt,
            "response": resp.answer,
            "confidence": conf,
            "answer_time_ms": resp.answer_time_ms,
            "training_value": challenge.training_value,
            "timestamp": time.time(),
            # Convert to training format for language model
            "training_example": self._to_training_format(challenge, resp.answer),
        }

        # Append to JSONL training file
        date_str = time.strftime("%Y-%m-%d")
        training_file = TRAINING_DIR / f"lyraauth_{date_str}.jsonl"
        try:
            with open(training_file, "a") as f:
                f.write(json.dumps(record) + "\n")
            self.training_records += 1
        except Exception as e:
            logger.error(f"Failed to store training record: {e}")

    def _to_training_format(self, challenge: Challenge, answer: str) -> Dict:
        """
        Convert challenge + answer to language model training format.
        Output: {"prompt": "...", "completion": "..."} — standard RLHF format.
        """
        if challenge.type == ChallengeType.WORD_COMPLETE:
            return {
                "prompt": challenge.prompt.replace("___", ""),
                "completion": answer,
                "type": "completion",
            }
        elif challenge.type == ChallengeType.ANALOGY:
            return {
                "prompt": challenge.prompt.replace("___", ""),
                "completion": answer,
                "type": "analogy_reasoning",
            }
        elif challenge.type == ChallengeType.SENTIMENT:
            orig = challenge.display_data.get("original_text", "")
            return {
                "prompt": orig,
                "completion": answer,
                "type": "sentiment_label",
            }
        elif challenge.type == ChallengeType.EMOJI_MEANING:
            return {
                "prompt": f"Describe the mood: {challenge.display_data.get('emoji', '')}",
                "completion": answer,
                "type": "semantic_description",
            }
        elif challenge.type == ChallengeType.BETTER_WORD:
            return {
                "prompt": f"Improve word choice: {challenge.display_data.get('sentence', '')}",
                "completion": answer,
                "type": "word_quality",
            }
        else:
            return {
                "prompt": challenge.prompt,
                "completion": answer,
                "type": challenge.type,
            }

    def _mint_token(self, site_key: str, session_id: str, confidence: float) -> str:
        """Issue a short-lived verification token the site can validate server-side."""
        payload = f"{site_key}:{session_id}:{confidence:.2f}:{int(time.time())}"
        token = hashlib.sha256(payload.encode()).hexdigest()[:32]
        return f"lyraauth_{token}"

    def get_training_stats(self) -> Dict:
        """How much training data has been collected."""
        total_records = 0
        files = list(TRAINING_DIR.glob("*.jsonl"))
        for f in files:
            try:
                with open(f) as fh:
                    total_records += sum(1 for _ in fh)
            except Exception:
                pass
        return {
            "challenges_served": self.challenges_served,
            "challenges_passed": self.challenges_passed,
            "training_records_today": self.training_records,
            "training_records_total": total_records,
            "training_files": len(files),
            "training_dir": str(TRAINING_DIR),
        }

    def export_training_data(self, date_str: Optional[str] = None) -> List[Dict]:
        """Export training data as list of {prompt, completion} dicts."""
        records = []
        pattern = f"lyraauth_{date_str}.jsonl" if date_str else "lyraauth_*.jsonl"
        for f in sorted(TRAINING_DIR.glob(pattern)):
            try:
                with open(f) as fh:
                    for line in fh:
                        record = json.loads(line)
                        if "training_example" in record:
                            records.append(record["training_example"])
            except Exception:
                pass
        return records


# Singleton
challenge_engine = ChallengeEngine()
