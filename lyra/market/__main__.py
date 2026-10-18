"""Command line: python -m lyra.market <command>

  read NVDA [--portfolio 10000] [--held 20]   Tremor reading + AI brief
  scan NVDA AAPL TSLA                         rank several tickers
  vix                                         current VIX
  news NVDA                                   pull and list the latest articles
  learn                                       grade matured predictions and retrain
  export NVDA AAPL --out signals.json         write a signal file for peers / GitHub
"""
import argparse
import asyncio
import json
import time

from lyra.market import expert, learner, news, peers
from lyra.market.market_data import get_vix


async def _main(args):
    if args.cmd == "read":
        r = await expert.analyze(args.tickers[0], args.portfolio, args.held)
        print(expert.ai_brief(r))
    elif args.cmd == "scan":
        for r in await expert.scan(args.tickers, args.portfolio):
            d = r["decision"]
            print(f"{r['label']:<12} score {r['score']:>5}  boom {r['p_boom']:.0%}  bust {r['p_bust']:.0%}  "
                  f"{d['action']:<4} conf {d['confidence']:.0%}")
    elif args.cmd == "vix":
        v = await get_vix()
        print(json.dumps({k: v[k] for k in v if k != "history"}, indent=2))
    elif args.cmd == "news":
        for a in await news.collect_news(args.tickers[0]):
            print(f"[{time.strftime('%Y-%m-%d', time.localtime(a['published']))}] {a['sentiment']:+.2f} "
                  f"{a['title']} — {a['source']}")
    elif args.cmd == "learn":
        print(await learner.evaluate_due())
    elif args.cmd == "export":
        data = peers.export_signals(await expert.scan(args.tickers))
        with open(args.out, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Wrote {len(data['signals'])} signals to {args.out}")


def main():
    p = argparse.ArgumentParser(prog="python -m lyra.market", description="Lyra Tremor Index")
    p.add_argument("cmd", choices=["read", "scan", "vix", "news", "learn", "export"])
    p.add_argument("tickers", nargs="*")
    p.add_argument("--portfolio", type=float)
    p.add_argument("--held", type=float, default=0.0)
    p.add_argument("--out", default="signals.json")
    args = p.parse_args()
    if args.cmd in ("read", "scan", "news", "export") and not args.tickers:
        p.error(f"{args.cmd} needs at least one ticker")
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
