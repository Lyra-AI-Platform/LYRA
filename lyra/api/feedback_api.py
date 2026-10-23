"""Feedback from the /feedback/ page.

  POST /api/feedback        anyone (signed in or not) sends a message; it is kept and emailed
  GET  /api/feedback        the owner (LYRA_ADMIN_EMAILS) reads the latest 200

Every message is stored first, so none is lost when email isn't set up or fails. It is then
emailed to LYRA_FEEDBACK_TO (default: the first LYRA_ADMIN_EMAILS address) by whichever is set:

  RESEND_API_KEY (+ LYRA_MAIL_FROM, a sender on a domain verified with Resend)
  SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD (+ LYRA_MAIL_FROM)

Bots are kept out by a hidden field, a minimum time on the page and per-address limits.
"""
import logging
import os
import smtplib
import ssl
import time
from email.message import EmailMessage
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from lyra.api import ratelimit, sessions
from lyra.api.users_api import EMAIL_RE, _admin_emails, get_current_user
from lyra.db.database import SessionLocal, get_db
from lyra.db.models import Feedback, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/feedback", tags=["feedback"])

KINDS = ("idea", "bug", "praise", "billing", "other")


class FeedbackIn(BaseModel):
    kind: str = "other"
    message: str
    email: str = ""
    rating: Optional[int] = None
    page: str = ""
    website: str = ""        # hidden; only bots fill it
    started_at: int = 0      # ms since epoch when the form was shown


def recipient() -> str:
    return os.getenv("LYRA_FEEDBACK_TO") or next(iter(sorted(_admin_emails())), "")


def _sender() -> str:
    return os.getenv("LYRA_MAIL_FROM", "Lyra feedback <feedback@lyraauth.com>")


def send_email(to: str, subject: str, text: str, reply_to: str = "") -> bool:
    """Send one plain-text email through Resend or SMTP. False when neither is set up or it fails."""
    if not to:
        return False
    try:
        if os.getenv("RESEND_API_KEY"):
            r = httpx.post("https://api.resend.com/emails", timeout=10,
                           headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
                           json={"from": _sender(), "to": [to], "subject": subject, "text": text,
                                 **({"reply_to": reply_to} if reply_to else {})})
            return r.status_code < 300
        if os.getenv("SMTP_HOST"):
            msg = EmailMessage()
            msg["From"], msg["To"], msg["Subject"] = _sender(), to, subject
            if reply_to:
                msg["Reply-To"] = reply_to
            msg.set_content(text)
            with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587")), timeout=15) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                if os.getenv("SMTP_USER"):
                    smtp.login(os.environ["SMTP_USER"], os.getenv("SMTP_PASSWORD", ""))
                smtp.send_message(msg)
            return True
    except Exception as e:  # noqa: BLE001 — the message is already stored; just log
        logger.warning("Feedback email failed: %s", e)
    return False


def _deliver(feedback_id: int) -> None:
    db = SessionLocal()
    try:
        f = db.query(Feedback).filter(Feedback.id == feedback_id).first()
        if not f:
            return
        stars = f"{f.rating}/5" if f.rating else "—"
        text = (f"{f.message}\n\n— — —\nType: {f.kind}\nRating: {stars}\nFrom: {f.email or 'anonymous'}"
                f"{' (signed in, user #' + str(f.user_id) + ')' if f.user_id else ''}\nPage: {f.page or '—'}\n"
                f"Reference: LF-{f.id:05d}")
        f.emailed = send_email(recipient(), f"[Lyra feedback · {f.kind}] {f.message[:60]}", text, f.email)
        db.commit()
    finally:
        db.close()


@router.post("", status_code=201)
def send(req: FeedbackIn, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    if not sessions.same_origin(request):
        raise HTTPException(403, "Refused: this request didn't come from lyraauth.com")
    ip = ratelimit.client_ip(request)
    ratelimit.check(f"feedback:{ip}", limit=5, window=600)
    ratelimit.check(f"feedback-day:{ip}", limit=30, window=86400)
    message = req.message.strip()
    if len(message) < 3:
        raise HTTPException(400, "Write a few words so we know what you mean")
    if len(message) > 5000:
        raise HTTPException(400, "Please keep it under 5,000 characters")
    email = req.email.strip().lower()[:254]
    if email and not EMAIL_RE.match(email):
        raise HTTPException(400, "That email address doesn't look right")
    user = sessions.user_from_cookie(request, db)
    # Hidden field filled, or sent faster than a person can type: say thanks, keep nothing.
    if req.website or (req.started_at and time.time() * 1000 - req.started_at < 2500):
        return {"ok": True, "reference": "LF-00000"}
    f = Feedback(kind=req.kind if req.kind in KINDS else "other", message=message,
                 email=email or (user.email if user else ""), user_id=user.id if user else None,
                 rating=req.rating if req.rating in (1, 2, 3, 4, 5) else None, page=req.page[:200],
                 ip=ip[:64], user_agent=(request.headers.get("user-agent") or "")[:200])
    db.add(f)
    db.commit()
    background.add_task(_deliver, f.id)
    return {"ok": True, "reference": f"LF-{f.id:05d}"}


@router.get("")
def latest(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.email.lower() not in _admin_emails():
        raise HTTPException(404, "Not Found")
    rows = db.query(Feedback).order_by(Feedback.id.desc()).limit(200).all()
    return [{"reference": f"LF-{r.id:05d}", "kind": r.kind, "message": r.message, "email": r.email,
             "rating": r.rating, "page": r.page, "emailed": r.emailed, "created_at": r.created_at} for r in rows]
