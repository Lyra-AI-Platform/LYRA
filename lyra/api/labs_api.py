"""Lyra Labs: plug in your own AI, or use Lyra's, or pair them 50/50, and point them at Lyra's
data. The apps (co-scientist, agent cooperative, intent pages, translator, story engine) run in
the browser (website/labs/), so they also work with a model on the visitor's own computer; the
server provides the model calls and the data.

  GET    /api/labs/status            what's available to this visitor
  GET    /api/labs/connections       the AIs this user has connected (keys never returned)
  POST   /api/labs/connections       connect one {name, kind: anthropic|openai, base_url, model, key}
  DELETE /api/labs/connections/{id}
  POST   /api/labs/complete          one model call {engine: "lyra" | connection id, system, messages, max_tokens}
  GET    /api/labs/context           newswire items to ground an answer (q, kind, topics, tickers, limit)
"""
import asyncio
import time
from typing import List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from lyra.api import entitlements, ratelimit
from lyra.api.users_api import get_current_user
from lyra.db.database import get_db
from lyra.db.models import LabsConnection, User
from lyra.labs import llm

router = APIRouter(prefix="/api/labs", tags=["labs"])

MAX_CONNECTIONS = 5
# The local model runs on the NAS's CPU: one answer at a time, everyone else waits in line.
_lyra_gate = asyncio.Semaphore(1)
LYRA_QUEUE_LIMIT = 6
_waiting = {"n": 0}

# Added to every call, whatever the app or model: Lyra Labs never helps anyone hurt people.
SAFETY = ("Safety rules that override everything else: never give instructions, quantities, synthesis routes or "
          "procurement help for weapons, explosives, chemical or biological agents, toxins, or anything meant to "
          "harm people; never help with surveillance of a private person, fraud or breaking into systems. For "
          "experiments, always include the hazards, required controls and a note that a qualified person must review "
          "and supervise the work. Never claim to have run an experiment, browsed a site or taken an action you did not.")


def _member(user: User, db: Session) -> bool:
    from lyra.api.page_access import is_member
    from lyra.api.watch_access import has_watch
    return is_member(user) or has_watch(user, db)


class ConnectionIn(BaseModel):
    name: str = Field("My AI", max_length=60)
    kind: str
    base_url: str = Field("", max_length=300)
    model: str = Field("", max_length=120)
    key: str = Field(..., min_length=8, max_length=400)


class Message(BaseModel):
    role: str
    content: str = Field(..., max_length=40000)


class CompleteIn(BaseModel):
    engine: Union[str, int] = "lyra"
    system: str = Field("", max_length=20000)
    messages: List[Message]
    max_tokens: int = 1500


def _row(c: LabsConnection):
    return {"id": c.id, "name": c.name, "kind": c.kind, "base_url": c.base_url, "model": c.model,
            "key": c.key_hint, "created_at": c.created_at}


@router.get("/status")
def status(request: Request, response: Response, db: Session = Depends(get_db)):
    from lyra.core import ollama_backend
    response.headers["Cache-Control"] = "no-store"
    user = entitlements.user_from_conn(request, db)
    return {"signed_in": bool(user), "member": bool(user and _member(user, db)),
            # Which model powers Lyra's AI is not disclosed to visitors (the owner sees it in /admin/).
            "lyra_model": {"on": ollama_backend.enabled(), "queue": _waiting["n"]},
            "default_claude": llm.DEFAULT_CLAUDE}


@router.get("/connections")
def list_connections(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(LabsConnection).filter(LabsConnection.user_id == user.id).order_by(LabsConnection.id).all()
    return [_row(c) for c in rows]


@router.post("/connections", status_code=201)
def add_connection(req: ConnectionIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if req.kind not in ("anthropic", "openai"):
        raise HTTPException(400, "kind must be anthropic or openai")
    if db.query(LabsConnection).filter(LabsConnection.user_id == user.id).count() >= MAX_CONNECTIONS:
        raise HTTPException(400, f"You can connect up to {MAX_CONNECTIONS} AIs. Remove one first.")
    base = ""
    if req.kind == "openai":
        try:
            base = llm.check_endpoint(req.base_url or "https://api.openai.com/v1")
        except llm.LLMError as e:
            raise HTTPException(400, str(e))
    c = LabsConnection(user_id=user.id, name=req.name.strip() or "My AI", kind=req.kind, base_url=base,
                       model=req.model.strip(), key_sealed=llm.seal(req.key.strip()), key_hint=llm.hint(req.key.strip()))
    db.add(c)
    db.commit()
    db.refresh(c)
    return _row(c)


@router.delete("/connections/{cid}")
def remove_connection(cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.query(LabsConnection).filter(LabsConnection.id == cid, LabsConnection.user_id == user.id).delete()
    db.commit()
    if not n:
        raise HTTPException(404, "No such connection")
    return {"ok": True}


@router.post("/complete")
async def complete(req: CompleteIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    messages = [{"role": m.role, "content": m.content} for m in req.messages if m.role in ("user", "assistant")][-20:]
    if not messages or messages[0]["role"] != "user":
        raise HTTPException(400, "The conversation must start with a user message")
    system = f"{SAFETY}\n\n{req.system}".strip()
    max_tokens = max(64, min(int(req.max_tokens or 1500), llm.MAX_OUTPUT))
    started = time.time()
    try:
        if str(req.engine) == "lyra":
            if not _member(user, db):
                raise HTTPException(402, {"error": "payment_required", "message": "Lyra's own model is for members. "
                                          "Start the free trial, or connect your own AI.", "upgrade_url": "/dashboard/billing.html"})
            ratelimit.check(f"labs-lyra:{user.id}", limit=30, window=3600)
            if _waiting["n"] >= LYRA_QUEUE_LIMIT:
                raise HTTPException(429, "Lyra's model is busy with other people's requests. Try again in a minute, or use your own AI.")
            _waiting["n"] += 1
            try:
                async with _lyra_gate:
                    text = await llm.complete(None, system, messages, max_tokens)
            finally:
                _waiting["n"] -= 1
            engine = "lyra"
        else:
            ratelimit.check(f"labs-own:{user.id}", limit=240, window=3600)
            c = db.query(LabsConnection).filter(LabsConnection.id == int(req.engine), LabsConnection.user_id == user.id).first()
            if not c:
                raise HTTPException(404, "That AI isn't connected to your account")
            text = await llm.complete({"kind": c.kind, "base_url": c.base_url, "model": c.model, "key": c.key_sealed},
                                      system, messages, max_tokens)
            engine = c.name
    except llm.LLMError as e:
        raise HTTPException(502, str(e))
    except ValueError:
        raise HTTPException(400, "Unknown engine")
    return {"text": text, "engine": engine, "seconds": round(time.time() - started, 1)}


@router.get("/context")
def context(request: Request, q: str = "", kind: str = "", topics: str = "", tickers: str = "", limit: int = 12,
            db: Session = Depends(get_db)):
    """Recent newswire items for grounding a model's answer in real, linked sources."""
    from lyra.newswire.store import get_wire
    user = entitlements.user_from_conn(request, db)
    n = min(max(limit, 1), 30 if user and _member(user, db) else 5)
    f = {"q": q[:200], "kind": kind[:20], "topics": topics[:40], "tickers": tickers[:12], "since": time.time() - 365 * 86400}
    rows = get_wire().relevant(q, f, limit=n) if q.strip() else get_wire().search(f, limit=n)["results"]
    return {"items": [{"title": r["title"], "url": r["url"], "source": r["source"], "kind": r["kind"],
                       "published": r["published"], "summary": (r["summary"] or "")[:300], "tickers": r["tickers"]}
                      for r in rows]}
