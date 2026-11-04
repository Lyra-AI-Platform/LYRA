"""Lyra Watch email alert settings, and unsubscribing without signing in."""
import json
import time
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from lyra import mail
from lyra.api import ratelimit
from lyra.api.users_api import get_current_user
from lyra.api.watch_access import has_watch
from lyra.db.database import get_db
from lyra.db.models import User, WatchAlert
from lyra.watch import alerts

router = APIRouter(prefix="/api/watch/alerts", tags=["watch-alerts"])


class AlertSettings(BaseModel):
    enabled: bool = False
    big_news: bool = True
    topics: List[str] = []
    frequency: str = "instant"     # instant | daily


def _limit(user: User, db: Session) -> int:
    return alerts.PRO_TOPICS if has_watch(user, db) else alerts.FREE_TOPICS


def _out(row, limit: int) -> dict:
    return {"enabled": bool(row and row.enabled), "big_news": bool(row.big_news) if row else True,
            "topics": json.loads(row.topics or "[]") if row else [], "frequency": row.frequency if row else "instant",
            "topic_limit": limit, "email_ready": mail.configured()}


def _confirm(email: str, token: str) -> None:
    body = ('<p style="margin:0 0 14px;">Your Lyra Watch alerts are on. We\'ll email you when something matches your '
            'choices, and never more than six times a day.</p>'
            f'<p style="margin:0;">{mail.button(mail.APP_URL + "/watch/account/#alerts", "Manage alerts")}</p>')
    unsub = f"{mail.APP_URL}/watch/unsubscribe/?token={token}"
    mail.send_email(email, "Your Lyra Watch alerts are on",
                    f"Your Lyra Watch alerts are on.\n\nManage alerts: {mail.APP_URL}/watch/account/#alerts\nUnsubscribe: {unsub}\n",
                    body_html=mail.page("Alerts are on", body, f'<div style="margin-bottom:8px;"><a href="{unsub}" style="color:#6e6b67;">Unsubscribe</a></div>'))


@router.get("")
def get_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.query(WatchAlert).filter(WatchAlert.user_id == user.id).first()
    return _out(row, _limit(user, db))


@router.put("")
def save_settings(req: AlertSettings, background: BackgroundTasks, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    if req.frequency not in ("instant", "daily"):
        raise HTTPException(400, "Choose as it happens or a daily summary")
    limit = _limit(user, db)
    row = db.query(WatchAlert).filter(WatchAlert.user_id == user.id).first()
    if not row:
        row = WatchAlert(user_id=user.id)
        db.add(row)
    switched_on = req.enabled and not row.enabled
    row.enabled, row.big_news, row.frequency = req.enabled, req.big_news, req.frequency
    row.topics = json.dumps(alerts.clean_topics(req.topics, limit))
    if switched_on:                # the record of consent, and nothing older than this is sent
        row.consented_at, row.cursor = time.time(), time.time()
    db.commit()
    if switched_on:
        background.add_task(_confirm, user.email, row.unsub_token)
    return _out(row, limit)


@router.post("/unsubscribe")
def unsubscribe(request: Request, token: str = "", db: Session = Depends(get_db)):
    """From the email footer or a mail app's one-click button. The token is the only credential."""
    ratelimit.check(f"alert-unsub:{ratelimit.client_ip(request)}", 30, 60)
    row = db.query(WatchAlert).filter(WatchAlert.unsub_token == token).first() if token else None
    if not row:
        raise HTTPException(404, "That unsubscribe link isn't valid")
    row.enabled = False
    db.commit()
    return {"ok": True}
