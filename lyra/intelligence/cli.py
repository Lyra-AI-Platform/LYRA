"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  LYRA Super-Intelligence — Terminal CLI                                      ║
║                                                                              ║
║  Commands:                                                                   ║
║    python -m lyra.intelligence.cli query "How does attention work?"          ║
║    python -m lyra.intelligence.cli ingest --fineweb 50000                   ║
║    python -m lyra.intelligence.cli ingest --starcoder 20000                 ║
║    python -m lyra.intelligence.cli ingest --file ./my_notes.pdf             ║
║    python -m lyra.intelligence.cli ingest --text "some text" --source blog  ║
║    python -m lyra.intelligence.cli stats                                     ║
║    python -m lyra.intelligence.cli chat                    # interactive    ║
║    python -m lyra.intelligence.cli train --scale small                      ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations
import argparse
import json
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def get_pipeline():
    from lyra.intelligence.super_pipeline import SuperPipeline
    pinecone_key  = os.getenv("PINECONE_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if not pinecone_key:
        print("\n[ERROR] PINECONE_API_KEY not set.")
        print("  export PINECONE_API_KEY=your-key-here")
        print("  Get your key at: https://app.pinecone.io (sign in with GitHub)\n")
        sys.exit(1)
    return SuperPipeline(pinecone_api_key=pinecone_key, anthropic_api_key=anthropic_key)


def cmd_query(args):
    pipe = get_pipeline()
    print(f"\nQuerying: {args.question}\n{'─'*60}")
    result = pipe.query(
        args.question,
        top_k=args.top_k,
        alpha=args.alpha,
        use_claude=not args.no_claude,
    )
    print("\n── Answer ──────────────────────────────────────────────────")
    print(result["answer"])
    print(f"\n── Sources ({result['chunks_retrieved']} retrieved, top {len(result['sources'])} shown) ──")
    for i, src in enumerate(result["sources"], 1):
        print(f"  [{i}] {src['source']} | rerank={src['rerank_score']:.4f} | {src['text'][:120]}...")
    print()


def cmd_ingest(args):
    pipe = get_pipeline()

    if args.fineweb:
        print(f"\nStreaming FineWeb-v2 ({args.fineweb:,} documents)...")
        print("This will take a while. Progress is logged every batch.\n")
        pipe.ingest_fineweb(max_docs=args.fineweb)
        print("\nFineWeb-v2 ingestion complete.")

    if args.starcoder:
        print(f"\nStreaming StarCoder2 ({args.starcoder:,} files)...")
        pipe.ingest_starcoder(max_docs=args.starcoder)
        print("\nStarCoder2 ingestion complete.")

    if args.file:
        print(f"\nIngesting file: {args.file}")
        pipe.ingest_file(args.file)
        print("File ingested.")

    if args.text:
        source = args.source or "cli"
        print(f"\nIngesting text (source='{source}')...")
        pipe.ingest_text(args.text, source=source)
        print("Text ingested.")

    if args.dataset:
        print(f"\nIngesting dataset: {args.dataset} (max {args.max_docs:,} docs)...")
        pipe.ingest_dataset(
            args.dataset,
            text_column=args.text_column or "text",
            max_docs=args.max_docs,
            config=args.config,
        )


def cmd_stats(args):
    pipe = get_pipeline()
    stats = pipe.stats()
    print("\n── Pinecone Index Stats ─────────────────────────────────────")
    print(json.dumps(stats, indent=2))


def cmd_chat(args):
    """Interactive REPL — type questions, get Chain-of-Thought answers."""
    pipe = get_pipeline()
    print("\n╔══════════════════════════════════════════╗")
    print("║  LYRA Super-Intelligence — Chat Mode      ║")
    print("║  Type your question. 'quit' to exit.      ║")
    print("╚══════════════════════════════════════════╝\n")

    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if not question:
            continue
        if question.lower() in ("quit", "exit", "q"):
            print("Bye.")
            break

        print("\nLyra: thinking...\n")
        try:
            result = pipe.query(question, use_claude=True)
            print(f"Lyra:\n{result['answer']}")
            if result["sources"]:
                print(f"\n  Sources: {', '.join(s['source'] for s in result['sources'][:3])}")
            print()
        except Exception as e:
            print(f"[Error] {e}\n")


def cmd_train(args):
    """Kick off LLM pre-training."""
    from lyra.intelligence.train_llm import train
    print(f"\nStarting LLM pre-training at scale='{args.scale}'")
    print("Press Ctrl+C to stop. Checkpoints are saved automatically.\n")
    train(scale=args.scale)


# ── Argument parser ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="lyra-intel",
        description="LYRA Super-Intelligence CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m lyra.intelligence.cli chat
  python -m lyra.intelligence.cli query "Explain transformer attention"
  python -m lyra.intelligence.cli ingest --fineweb 50000
  python -m lyra.intelligence.cli ingest --file ./research.pdf
  python -m lyra.intelligence.cli ingest --text "My own notes" --source notes
  python -m lyra.intelligence.cli stats
  python -m lyra.intelligence.cli train --scale test
        """,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # query
    p_query = sub.add_parser("query", help="Ask a question")
    p_query.add_argument("question", help="The question to ask")
    p_query.add_argument("--top-k",    type=int,   default=5,   help="Results to return (default 5)")
    p_query.add_argument("--alpha",    type=float, default=0.7, help="Dense vs sparse weight 0-1 (default 0.7)")
    p_query.add_argument("--no-claude", action="store_true",    help="Skip Claude, return raw chunks only")

    # ingest
    p_ingest = sub.add_parser("ingest", help="Ingest data into Pinecone")
    p_ingest.add_argument("--fineweb",    type=int,    help="Ingest N docs from FineWeb-v2")
    p_ingest.add_argument("--starcoder",  type=int,    help="Ingest N files from StarCoder2")
    p_ingest.add_argument("--file",       type=str,    help="Ingest a local file (PDF/TXT/JSONL/MD)")
    p_ingest.add_argument("--text",       type=str,    help="Ingest a raw text string")
    p_ingest.add_argument("--source",     type=str,    help="Source label for --text ingestion")
    p_ingest.add_argument("--dataset",    type=str,    help="HuggingFace dataset name")
    p_ingest.add_argument("--max-docs",   type=int,    default=10_000, help="Max docs for --dataset")
    p_ingest.add_argument("--text-column",type=str,    help="Column name for --dataset")
    p_ingest.add_argument("--config",     type=str,    help="Dataset config/subset name")

    # stats
    sub.add_parser("stats", help="Show Pinecone index statistics")

    # chat
    sub.add_parser("chat", help="Interactive chat mode (REPL)")

    # train
    p_train = sub.add_parser("train", help="Pre-train Lyra LLM from scratch")
    p_train.add_argument(
        "--scale",
        choices=["test", "small", "medium", "large", "production"],
        default="small",
        help="Model scale (test=50M, small=400M, medium=3B, large=13B, production=22B)",
    )

    args = parser.parse_args()

    if args.cmd == "query":   cmd_query(args)
    elif args.cmd == "ingest": cmd_ingest(args)
    elif args.cmd == "stats":  cmd_stats(args)
    elif args.cmd == "chat":   cmd_chat(args)
    elif args.cmd == "train":  cmd_train(args)


if __name__ == "__main__":
    main()
