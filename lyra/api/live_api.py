"""Live, fed by the Newswire pipeline.

  GET  /api/pulse/live?channel=&sort=importance|time&q=&mine=1   grouped stories and Tremor spikes.
       Subscribers get them as they land; visitors see the same feed an hour behind.
  GET  /api/pulse/leaderboard      Companies with unusual activity (public)
  GET/POST/DELETE /api/pulse/follows   My Live: people, companies, topics, saved searches (Markets Pro)
"""
import hashlib
import time
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from lyra.api import entitlements, ratelimit
from lyra.db.database import get_db
from lyra.db.models import LiveFollow, User
from lyra.market import live_events
from lyra.market.pulse_loop import pulse_loop
from lyra.newswire.store import get_wire

router = APIRouter(prefix="/api/pulse", tags=["live"])

PUBLIC_DELAY = 3600
PAGE = 60
KINDS = ("person", "company", "topic", "search")
MAX_FOLLOWS = 100
_online: Dict[str, float] = {}


def watching() -> int:
    """Everyone with the page open: polling viewers. The stream's viewers are added by the caller."""
    return live_events.viewers_online(_online)


def _full(user: Optional[User], db: Session) -> bool:
    from lyra.api.watch_access import has_watch
    return entitlements.has_markets(user) or has_watch(user, db)


def _follows(user: User, db: Session) -> List[Dict]:
    return [{"id": r.id, "kind": r.kind, "value": r.value, "label": r.label or r.value, "alerts": bool(r.alerts)}
            for r in db.query(LiveFollow).filter(LiveFollow.user_id == user.id).all()]


@router.get("/live")
def live(request: Request, response: Response, channel: str = "", sort: str = "importance", q: str = "", mine: bool = False,
         limit: int = PAGE, db: Session = Depends(get_db)):
    _online[hashlib.sha256(ratelimit.client_ip(request).encode()).hexdigest()[:16]] = time.time()
    user = entitlements.user_from_conn(request, db)
    full = _full(user, db)
    if mine and not entitlements.has_markets(user):
        raise HTTPException(402, {"error": "payment_required", "feature": "my_live", "upgrade_url": "/pricing/"})
    now = time.time()
    until = None if full else now - PUBLIC_DELAY
    limit = min(max(limit, 1), PAGE)
    f = {"since": now - 86400, "until": until, "channel": channel[:30], "q": q[:80]}
    rows = get_wire().clusters(f, limit=400 if mine else limit, by_importance=sort != "time")
    if mine:
        followed = _follows(user, db)
        rows = [c for c in rows if any(live_events.matches(x, c) for x in followed)][:limit]
    from lyra.watch.live import hub
    spikes = [e for e in hub.recent(100, delay=0 if full else PUBLIC_DELAY, include_x=False) if e.get("kind") == "tremor_spike"]
    response.headers["Cache-Control"] = "private, no-store"
    return {"full": full, "delay_seconds": 0 if full else PUBLIC_DELAY, "stories": rows, "spikes": spikes[:3]}


@router.get("/leaderboard")
def board(response: Response):
    response.headers["Cache-Control"] = "public, max-age=30"
    if not pulse_loop.board and not pulse_loop.updated:
        pulse_loop.refresh_board()
    return {"rows": pulse_loop.board, "updated": pulse_loop.updated}


class FollowIn(BaseModel):
    kind: str
    value: str
    label: str = ""
    alerts: bool = False


@router.get("/follows")
def list_follows(user: User = Depends(entitlements.require_markets("my_live")), db: Session = Depends(get_db)):
    return {"follows": _follows(user, db)}


@router.post("/follows", status_code=201)
def add_follow(body: FollowIn, user: User = Depends(entitlements.require_markets("my_live")), db: Session = Depends(get_db)):
    value = body.value.strip()[:120]
    if body.kind not in KINDS or not value:
        raise HTTPException(400, "Follow a person, company, topic or search.")
    if body.kind == "company":
        value = value.upper()
    row = db.query(LiveFollow).filter(LiveFollow.user_id == user.id, LiveFollow.kind == body.kind, LiveFollow.value == value).first()
    if not row:
        if db.query(LiveFollow).filter(LiveFollow.user_id == user.id).count() >= MAX_FOLLOWS:
            raise HTTPException(400, f"You can follow up to {MAX_FOLLOWS} things.")
        row = LiveFollow(user_id=user.id, kind=body.kind, value=value)
        db.add(row)
    row.label, row.alerts = body.label.strip()[:120], body.alerts
    db.commit()
    return {"follows": _follows(user, db)}


@router.delete("/follows/{follow_id}")
def remove_follow(follow_id: int, user: User = Depends(entitlements.require_markets("my_live")), db: Session = Depends(get_db)):
    db.query(LiveFollow).filter(LiveFollow.id == follow_id, LiveFollow.user_id == user.id).delete()
    db.commit()
    return {"follows": _follows(user, db)}
