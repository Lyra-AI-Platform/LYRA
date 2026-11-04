"""
Sending email, and the one template every customer email uses.

Set RESEND_API_KEY, or SMTP_HOST, SMTP_PORT (587), SMTP_USER and SMTP_PASSWORD. The sender is
LYRA_MAIL_FROM (default "Lyra <support@lyraauth.com>"). Alerts can use their own sender with
LYRA_ALERTS_FROM. LYRA_MAIL_ADDRESS adds a postal address to the footer.
"""
import html
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Dict, Optional

import httpx

logger = logging.getLogger(__name__)
APP_URL = os.getenv("APP_URL", "https://lyraauth.com")


def sender() -> str:
    return os.getenv("LYRA_MAIL_FROM", "Lyra <support@lyraauth.com>")


def configured() -> bool:
    return bool(os.getenv("RESEND_API_KEY") or os.getenv("SMTP_HOST"))


def send_email(to: str, subject: str, text: str, reply_to: str = "", body_html: str = "",
               headers: Optional[Dict[str, str]] = None, from_addr: str = "") -> bool:
    """Send one email through Resend or SMTP. False when neither is set up or it fails."""
    if not to:
        return False
    subject = " ".join(subject.split())   # no line breaks reach a mail header
    origin = from_addr or sender()
    try:
        if os.getenv("RESEND_API_KEY"):
            r = httpx.post("https://api.resend.com/emails", timeout=10,
                           headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
                           json={"from": origin, "to": [to], "subject": subject, "text": text,
                                 **({"html": body_html} if body_html else {}),
                                 **({"headers": headers} if headers else {}),
                                 **({"reply_to": reply_to} if reply_to else {})})
            if r.status_code >= 300:
                logger.warning("Resend refused an email: %s", r.status_code)
            return r.status_code < 300
        if os.getenv("SMTP_HOST"):
            msg = EmailMessage()
            msg["From"], msg["To"], msg["Subject"] = origin, to, subject
            if reply_to:
                msg["Reply-To"] = reply_to
            for name, value in (headers or {}).items():
                msg[name] = value
            msg.set_content(text)
            if body_html:
                msg.add_alternative(body_html, subtype="html")
            with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587")), timeout=15) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                if os.getenv("SMTP_USER"):
                    smtp.login(os.environ["SMTP_USER"], os.getenv("SMTP_PASSWORD", ""))
                smtp.send_message(msg)
            return True
    except Exception as e:  # noqa: BLE001 — callers decide what a failed send means
        logger.warning("Email failed: %s", e)
    return False


def button(url: str, label: str) -> str:
    return (f'<a href="{html.escape(url, quote=True)}" style="display:inline-block;background:#14120e;color:#faf9f7;'
            f'text-decoration:none;font-weight:600;font-size:15px;padding:12px 22px;border-radius:8px;">'
            f'{html.escape(label)}</a>')


def page(heading: str, body: str, footer: str = "") -> str:
    """A complete email. `body` and `footer` are trusted HTML, so escape what goes into them."""
    address = html.escape(os.getenv("LYRA_MAIL_ADDRESS", ""))
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f2ee;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f2ee;padding:32px 12px;">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border:1px solid #e6e2db;border-radius:12px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#14120e;">
<tr><td style="padding:24px 32px 0;font-size:17px;font-weight:700;letter-spacing:-.01em;">Lyra</td></tr>
<tr><td style="padding:18px 32px 28px;font-size:15px;line-height:1.6;">
<h1 style="margin:0 0 14px;font-size:22px;line-height:1.3;font-weight:700;">{html.escape(heading)}</h1>
{body}
</td></tr>
<tr><td style="padding:18px 32px 24px;border-top:1px solid #eee9e1;font-size:12px;line-height:1.6;color:#6e6b67;">
{footer}
<div>Lyra Labs · <a href="{APP_URL}" style="color:#6e6b67;">lyraauth.com</a>{' · ' + address if address else ''}</div>
</td></tr>
</table>
</td></tr></table>
</body></html>"""
