"""
LyraAuth Training Pipeline
Converts collected challenge responses into training data for Lyra's own LLM.

Flow:
  LyraAuth responses (JSONL)
    → clean + filter
    → format as instruction-tuning pairs
    → feed into Lyra's language backbone
    → eventually fine-tune a small model (125M-500M params)

This is how Lyra grows its OWN language model from crowd-sourced human input —
no dependency on OpenAI, Anthropic, or Meta. Pure self-training.

Training milestone estimates (with LyraAuth deployed on websites):
  10 sites × 100 users/day    =    1,000 examples/day →  ~1 week to 10K examples
  100 sites × 500 users/day   =   50,000 examples/day →  fine-tunable in days
  1,000 sites × 1K users/day  = 1,000,000 examples/day → GPT-2 level in weeks
"""
import json
import logging
import random
from pathlib import Path
from typing import Dict, Generator, List, Optional

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "auth"
TRAINING_DIR = DATA_DIR / "training_data"
PROCESSED_DIR = DATA_DIR / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


class TrainingDataPipeline:
    """
    Processes LyraAuth challenge responses into language model training data.
    Supports multiple output formats:
      - instruction_following: {"instruction": ..., "response": ...}
      - completion: {"prompt": ..., "completion": ...}
      - preference: {"prompt": ..., "chosen": ..., "rejected": ...}  (for RLHF)
    """

    QUALITY_MIN_LENGTH = 2          # minimum answer length (chars)
    QUALITY_MAX_TIME_MS = 60_000    # reject if answered in > 1 min (distracted)
    QUALITY_MIN_TIME_MS = 500       # reject if answered in < 0.5s (bot)
    MIN_CONFIDENCE = 0.7            # only use high-confidence human responses

    def __init__(self):
        self.processed = 0
        self.rejected = 0
        self.total_examples = 0

    def process_all(self, output_format: str = "instruction_following") -> Path:
        """
        Process all collected JSONL files into a single training dataset.
        Returns path to output file.
        """
        output_file = PROCESSED_DIR / f"lyra_training_{output_format}.jsonl"

        with open(output_file, "w") as out:
            for record in self._iter_raw_records():
                example = self._convert(record, output_format)
                if example:
                    out.write(json.dumps(example) + "\n")
                    self.processed += 1
                else:
                    self.rejected += 1

        self.total_examples = self.processed
        logger.info(
            f"Training pipeline complete: {self.processed} examples, "
            f"{self.rejected} rejected → {output_file}"
        )
        return output_file

    def _iter_raw_records(self) -> Generator[Dict, None, None]:
        """Iterate over all raw JSONL training records."""
        if not TRAINING_DIR.exists():
            return
        for f in sorted(TRAINING_DIR.glob("lyraauth_*.jsonl")):
            try:
                with open(f) as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            try:
                                yield json.loads(line)
                            except json.JSONDecodeError:
                                pass
            except Exception as e:
                logger.warning(f"Failed to read {f}: {e}")

    def _convert(self, record: Dict, fmt: str) -> Optional[Dict]:
        """Convert a raw record to the target format. Returns None if rejected."""
        # Quality filters
        answer = record.get("response", "").strip()
        conf = record.get("confidence", 0.0)
        time_ms = record.get("answer_time_ms", 0)
        t_value = record.get("training_value", 1.0)

        if not answer or len(answer) < self.QUALITY_MIN_LENGTH:
            return None
        if conf < self.MIN_CONFIDENCE:
            return None
        if time_ms < self.QUALITY_MIN_TIME_MS or time_ms > self.QUALITY_MAX_TIME_MS:
            return None

        prompt = record.get("prompt", "").strip()
        if not prompt:
            return None

        ex = record.get("training_example", {})
        ctype = record.get("type", "unknown")

        if fmt == "instruction_following":
            return self._to_instruction(ctype, prompt, answer, ex)
        elif fmt == "completion":
            return {
                "prompt": ex.get("prompt", prompt),
                "completion": answer,
                "type": ctype,
                "quality": round(conf * t_value, 2),
            }
        elif fmt == "preference":
            return self._to_preference(ctype, prompt, answer, ex)
        else:
            return {"text": f"Human: {prompt}\nAssistant: {answer}"}

    def _to_instruction(self, ctype: str, prompt: str, answer: str, ex: Dict) -> Dict:
        """Format as instruction-following pair."""
        instructions = {
            "word_complete":  "Complete the sentence naturally.",
            "analogy":        "Solve this analogy.",
            "sentiment":      "Label the sentiment of this text.",
            "common_sense":   "Answer this common-sense question.",
            "sequence":       "Identify the next element in the sequence.",
            "better_word":    "Replace the highlighted word with a more precise alternative.",
            "emoji_meaning":  "Describe the mood or concept these emojis represent.",
            "fact_check":     "Evaluate whether this claim is plausible.",
            "ranking":        "Rank these options from best to worst.",
        }
        instruction = instructions.get(ctype, "Answer the following.")
        return {
            "instruction": instruction,
            "input": ex.get("prompt", prompt),
            "output": answer,
            "type": ctype,
        }

    def _to_preference(self, ctype: str, prompt: str, answer: str, ex: Dict) -> Optional[Dict]:
        """
        Format as preference pair for RLHF.
        We mark human answers as 'chosen' and generate a plausible 'rejected' answer.
        Note: real RLHF needs pairs of model responses — this is a bootstrap approach.
        """
        rejected_answers = {
            "word_complete":  ["um", "something", "idk", "whatever"],
            "analogy":        ["maybe", "both", "neither", "all of them"],
            "sentiment":      ["I don't know", "Could be either", "Not sure"],
            "emoji_meaning":  ["emojis", "symbols", "icons", "things"],
        }
        rejects = rejected_answers.get(ctype, ["I don't know", "unclear", "N/A"])
        return {
            "prompt": ex.get("prompt", prompt),
            "chosen": answer,
            "rejected": random.choice(rejects),
            "type": ctype,
        }

    def get_stats(self) -> Dict:
        """Statistics about available training data."""
        raw_count = 0
        type_counts: Dict[str, int] = {}

        for record in self._iter_raw_records():
            raw_count += 1
            ctype = record.get("type", "unknown")
            type_counts[ctype] = type_counts.get(ctype, 0) + 1

        processed_files = list(PROCESSED_DIR.glob("*.jsonl"))
        processed_count = 0
        for f in processed_files:
            try:
                with open(f) as fh:
                    processed_count += sum(1 for _ in fh)
            except Exception:
                pass

        # Estimate training viability
        viability = "not yet — need 10,000+ examples"
        if raw_count >= 100_000:
            viability = "YES — ready for full fine-tuning"
        elif raw_count >= 10_000:
            viability = "YES — ready for LoRA fine-tuning of small model"
        elif raw_count >= 1_000:
            viability = "PARTIAL — enough to tune language backbone"

        return {
            "raw_records": raw_count,
            "processed_records": processed_count,
            "type_breakdown": type_counts,
            "training_viability": viability,
            "milestones": {
                "current": raw_count,
                "language_backbone_tune": 1_000,
                "lora_finetune_125m": 10_000,
                "full_finetune_125m": 50_000,
                "train_from_scratch_125m": 500_000,
                "gpt2_scale": 1_000_000,
            },
        }

    def feed_to_backbone(self, limit: int = 500):
        """
        Feed collected examples to the language backbone's Markov chain.
        Instant improvement — no GPU needed.
        """
        try:
            from lyra.core.language_backbone import language_backbone
            count = 0
            for record in self._iter_raw_records():
                prompt = record.get("prompt", "")
                answer = record.get("response", "")
                if prompt and answer:
                    language_backbone.read_and_learn(f"{prompt} {answer}")
                    count += 1
                if count >= limit:
                    break
            logger.info(f"Fed {count} LyraAuth examples to language backbone")
            return count
        except Exception as e:
            logger.error(f"Backbone feed failed: {e}")
            return 0


# Singleton
training_pipeline = TrainingDataPipeline()
