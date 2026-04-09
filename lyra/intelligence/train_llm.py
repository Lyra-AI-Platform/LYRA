"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  LYRA — Custom LLM Pre-Training Pipeline                                     ║
║                                                                              ║
║  Trains a Mixture-of-Experts causal LLM from scratch on:                    ║
║    • FineWeb-v2  (15T+ tokens of curated web text)                           ║
║    • StarCoder2  (code across 600+ languages)                                ║
║    Mix: 70% general web, 30% code — same ratio as Claude/GPT-4 training.    ║
║                                                                              ║
║  Run:                                                                        ║
║    # Single GPU:                                                             ║
║    python -m lyra.intelligence.train_llm                                     ║
║                                                                              ║
║    # Multi-GPU (recommended for real training):                              ║
║    torchrun --nproc_per_node=4 -m lyra.intelligence.train_llm               ║
║                                                                              ║
║  Requirements:                                                               ║
║    pip install torch transformers datasets accelerate wandb trl xformers    ║
║    pip install flash-attn --no-build-isolation   # optional, big speedup    ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
os.environ.setdefault("WANDB_PROJECT", "lyra-llm-pretraining")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Base architecture — we start from Mixtral's tokenizer + config blueprint
# but initialise ALL weights randomly (true from-scratch training)
BASE_ARCH        = "mistralai/Mixtral-8x7B-v0.1"
OUTPUT_DIR       = str(Path(__file__).parent.parent.parent / "data" / "llm-checkpoints")
FINAL_DIR        = str(Path(__file__).parent.parent.parent / "data" / "llm-final")
MAX_SEQ_LEN      = 4096
FINEWEB_SNAPSHOT = "CC-MAIN-2024-10"   # Use most recent crawl

# ── Model scale presets ───────────────────────────────────────────────────────
# Choose based on your hardware. Start with "test" or "small" locally.
MODEL_SCALES = {
    "test":       dict(hidden=512,   layers=4,  heads=8,  experts=2, params="~50M"),
    "small":      dict(hidden=1024,  layers=8,  heads=8,  experts=4, params="~400M"),
    "medium":     dict(hidden=2048,  layers=16, heads=16, experts=4, params="~3B"),
    "large":      dict(hidden=4096,  layers=24, heads=32, experts=8, params="~13B"),
    "production": dict(hidden=4096,  layers=32, heads=32, experts=8, params="~22B"),
}

TRAINING_CONFIGS = {
    "test":       dict(steps=500,    batch=2,  accum=4,  lr=3e-4, workers=0),
    "small":      dict(steps=10_000, batch=4,  accum=8,  lr=3e-4, workers=2),
    "medium":     dict(steps=50_000, batch=4,  accum=16, lr=2e-4, workers=4),
    "large":      dict(steps=100_000,batch=2,  accum=32, lr=1e-4, workers=4),
    "production": dict(steps=500_000,batch=2,  accum=64, lr=1e-4, workers=4),
}


# ── Architecture initialisation ───────────────────────────────────────────────

def build_model(scale: str = "small"):
    """Build a fresh MoE LLM with random weights at the chosen scale."""
    from transformers import AutoConfig, AutoModelForCausalLM

    cfg = MODEL_SCALES[scale]
    logger.info(f"Building {scale} model (~{cfg['params']} params)...")

    config = AutoConfig.from_pretrained(BASE_ARCH, trust_remote_code=True)

    # Override architecture dimensions
    config.hidden_size              = cfg["hidden"]
    config.num_hidden_layers        = cfg["layers"]
    config.num_attention_heads      = cfg["heads"]
    config.num_key_value_heads      = max(1, cfg["heads"] // 4)   # GQA
    config.intermediate_size        = cfg["hidden"] * 4
    config.num_local_experts        = cfg["experts"]
    config.num_experts_per_tok      = min(2, cfg["experts"])
    config.max_position_embeddings  = MAX_SEQ_LEN
    config.sliding_window           = MAX_SEQ_LEN

    # Random init — no pretrained weights
    model = AutoModelForCausalLM.from_config(config)
    num_params = sum(p.numel() for p in model.parameters()) / 1e9
    logger.info(f"Model ready: {num_params:.2f}B parameters (random init)")
    return model


# ── Streaming dataset ─────────────────────────────────────────────────────────

def build_dataset(tokenizer, scale: str = "small"):
    """
    Stream FineWeb-v2 + StarCoder2, interleaved 70/30.
    Tokenised on-the-fly — never loads full dataset into RAM.
    """
    from datasets import load_dataset, interleave_datasets

    logger.info("Connecting to FineWeb-v2 stream...")
    try:
        fineweb = load_dataset(
            "HuggingFaceFW/fineweb-v2",
            name=FINEWEB_SNAPSHOT,
            split="train",
            streaming=True,
            trust_remote_code=True,
        ).select_columns(["text"])
    except Exception as e:
        logger.warning(f"FineWeb-v2 unavailable ({e}), falling back to FineWeb-Edu...")
        fineweb = load_dataset(
            "HuggingFaceFW/fineweb-edu",
            split="train",
            streaming=True,
            trust_remote_code=True,
        ).select_columns(["text"])

    logger.info("Connecting to StarCoder2 stream...")
    try:
        starcoder = load_dataset(
            "bigcode/the-stack-v2-train-smol-ids",
            split="train",
            streaming=True,
            trust_remote_code=True,
        ).map(lambda x: {"text": x.get("content", x.get("text", ""))}).select_columns(["text"])
    except Exception as e:
        logger.warning(f"StarCoder unavailable ({e}), using Python subset only...")
        starcoder = load_dataset(
            "bigcode/the-stack",
            data_dir="data/python",
            split="train",
            streaming=True,
            trust_remote_code=True,
        ).map(lambda x: {"text": x.get("content", "")}).select_columns(["text"])

    # 70% web, 30% code — same as frontier model training ratios
    mixed = interleave_datasets([fineweb, starcoder], probabilities=[0.7, 0.3], seed=42)

    def tokenize(examples):
        out = tokenizer(
            examples["text"],
            truncation=True,
            max_length=MAX_SEQ_LEN,
            padding="max_length",
            return_special_tokens_mask=True,
        )
        return out

    tokenized = mixed.map(tokenize, batched=True, remove_columns=["text"])
    logger.info("Dataset streams ready.")
    return tokenized


# ── Training ──────────────────────────────────────────────────────────────────

def train(scale: str = "small"):
    """Main training entry point."""
    import torch
    from transformers import (
        AutoTokenizer,
        DataCollatorForLanguageModeling,
        Trainer,
        TrainingArguments,
    )

    # GPU check
    if not torch.cuda.is_available():
        logger.warning(
            "No CUDA GPU detected. Training will be VERY slow on CPU. "
            "Use scale='test' for a quick smoke-test, or run on a GPU machine."
        )

    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    Path(FINAL_DIR).mkdir(parents=True, exist_ok=True)

    tc  = TRAINING_CONFIGS[scale]
    use_bf16 = torch.cuda.is_available() and torch.cuda.get_device_capability()[0] >= 8

    logger.info(f"Scale: {scale} | Steps: {tc['steps']:,} | bf16: {use_bf16}")

    # Tokenizer (reuse Mixtral's — 32k vocab, good multilingual coverage)
    logger.info("Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(BASE_ARCH, trust_remote_code=True)
    tokenizer.pad_token = tokenizer.eos_token

    # Model
    model = build_model(scale)

    # Dataset
    train_ds = build_dataset(tokenizer, scale)

    # Collator — causal LM (next token prediction)
    collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)

    # Training args
    training_args = TrainingArguments(
        output_dir=OUTPUT_DIR,
        max_steps=tc["steps"],
        per_device_train_batch_size=tc["batch"],
        gradient_accumulation_steps=tc["accum"],
        learning_rate=tc["lr"],
        weight_decay=0.1,
        warmup_ratio=0.02,
        lr_scheduler_type="cosine",
        bf16=use_bf16,
        fp16=not use_bf16 and torch.cuda.is_available(),
        logging_steps=25,
        save_steps=max(500, tc["steps"] // 20),
        save_total_limit=3,
        report_to="wandb" if os.getenv("WANDB_API_KEY") else "none",
        dataloader_num_workers=tc["workers"],
        gradient_checkpointing=True,   # saves ~40% VRAM
        optim="adamw_torch_fused" if torch.cuda.is_available() else "adamw_torch",
        remove_unused_columns=False,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        data_collator=collator,
    )

    logger.info("=" * 60)
    logger.info("  LYRA LLM Pre-training starting")
    logger.info(f"  Scale:   {scale}")
    logger.info(f"  Steps:   {tc['steps']:,}")
    logger.info(f"  Output:  {OUTPUT_DIR}")
    logger.info("=" * 60)

    trainer.train()

    logger.info("Saving final model...")
    trainer.save_model(FINAL_DIR)
    tokenizer.save_pretrained(FINAL_DIR)
    logger.info(f"Done. Model saved to {FINAL_DIR}")


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Train Lyra LLM from scratch")
    parser.add_argument(
        "--scale",
        choices=list(MODEL_SCALES.keys()),
        default="small",
        help=(
            "Model scale to train: "
            "test=50M (local smoke-test), "
            "small=400M (single GPU), "
            "medium=3B (multi-GPU), "
            "large=13B (A100 cluster), "
            "production=22B (full run)"
        ),
    )
    args = parser.parse_args()

    scales_info = "\n".join(
        f"  {k:12s} ~{v['params']:6s}  steps={TRAINING_CONFIGS[k]['steps']:,}"
        for k, v in MODEL_SCALES.items()
    )
    print(f"\nAvailable scales:\n{scales_info}\n")
    print(f"Running scale: {args.scale}\n")

    train(scale=args.scale)
