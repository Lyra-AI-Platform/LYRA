"""Signal network ("neurolink"): cross-checks this node's view against other
systems — other Lyra nodes, or signal files that other projects publish on
GitHub — so one bad data source can't dominate a decision.

Configure peers in data/market/peers.json, e.g.
[
  {"name": "friend-node", "type": "lyra", "url": "https://friend.example", "key": "<their LYRA_PEER_KEY>", "weight": 1.0},
  {"name": "some-repo", "type": "json", "weight": 0.5,
   "url": "https://raw.githubusercontent.com/<owner>/<repo>/main/signals.json"}
]
A "json" peer publishes the same shape that export_signals() writes:
{"generated_at": ..., "signals": {"NVDA": {"p_boom": 0.6, "p_bust": 0.2, "ts": ...}}}
"""
import asyncio
import json
import time
from typing import Dict, List

from lyra.market.config import INDEX_CODE, load_peers
from lyra.market.fetch import fetch_text

MAX_SIGNAL_AGE = 3 * 86400


def _clean(sig: Dict) -> Dict:
    try:
        p_boom, p_bust = float(sig["p_boom"]), float(sig["p_bust"])
    except (KeyError, TypeError, ValueError):
        return {}
    if not (0 <= p_boom <= 1 and 0 <= p_bust <= 1):
        return {}
    if time.time() - float(sig.get("ts", time.time())) > MAX_SIGNAL_AGE:
        return {}
    return {"p_boom": p_boom, "p_bust": p_bust}


async def _peer_signal(peer: Dict, ticker: str) -> Dict:
    if peer.get("type") == "lyra":
        body = await fetch_text(f"{peer['url'].rstrip('/')}/api/market/signal/{ticker}", max_age=1800, timeout=8,
                                headers={"X-Lyra-Peer-Key": peer.get("key", "")})
        sig = json.loads(body) if body else {}
    else:
        body = await fetch_text(peer["url"], max_age=1800, timeout=8)
        sig = (json.loads(body).get("signals", {}) if body else {}).get(ticker.upper(), {})
    clean = _clean(sig)
    return {"peer": peer.get("name", peer["url"]), "weight": float(peer.get("weight", 1.0)), **clean} if clean else {}


async def consult(ticker: str) -> Dict:
    """Weighted consensus of peers: edge in [-1, 1] and how much they disagree."""
    peers = load_peers()
    if not peers:
        return {"peers": [], "edge": 0.0, "disagreement": 0.0}
    results = await asyncio.gather(*(_peer_signal(p, ticker) for p in peers), return_exceptions=True)
    sigs: List[Dict] = [r for r in results if isinstance(r, dict) and r]
    if not sigs:
        return {"peers": [], "edge": 0.0, "disagreement": 0.0}
    total = sum(s["weight"] for s in sigs)
    edges = [s["p_boom"] - s["p_bust"] for s in sigs]
    edge = sum(s["weight"] * e for s, e in zip(sigs, edges)) / total
    spread = max(edges) - min(edges) if len(edges) > 1 else 0.0
    return {"peers": sigs, "edge": round(edge, 4), "disagreement": round(spread / 2, 4)}


def export_signals(readings: List[Dict]) -> Dict:
    """Shape our own readings so other nodes (or a GitHub repo) can consume them."""
    return {
        "index": INDEX_CODE,
        "generated_at": time.time(),
        "signals": {r["ticker"]: {"p_boom": r["p_boom"], "p_bust": r["p_bust"], "score": r["score"],
                                  "action": r["decision"]["action"], "ts": r["created_at"]}
                    for r in readings},
    }
