"""Consent-based newsletter with double opt-in and Brevo delivery.

Subscribers live in growth.db (separate from users/chats). A signup is only
mailed after the confirmation link is clicked; unsubscribes remove the contact
from the Brevo list.
"""

from __future__ import annotations

import html
import json
import logging
import re
import secrets
import sqlite3
import time
from pathlib import Path

import requests

from config import (
    BREVO_API_KEY,
    BREVO_LIST_ID,
    GSC_DB_PATH,
    NEWSLETTER_FROM_EMAIL,
    NEWSLETTER_FROM_NAME,
    NEWSLETTER_REPLY_TO,
    SITE_URL,
)

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS subscribers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'pending',
    token           TEXT NOT NULL UNIQUE,
    source          TEXT NOT NULL DEFAULT '',
    created_at      REAL NOT NULL,
    confirmed_at    REAL,
    unsubscribed_at REAL
);
CREATE INDEX IF NOT EXISTS idx_subscribers_status ON subscribers(status);
"""


def _connection():
    path = Path(GSC_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def configured() -> bool:
    return bool(BREVO_API_KEY and BREVO_LIST_ID and NEWSLETTER_FROM_EMAIL)


def _valid_email(value: str) -> str:
    email = str(value or "").strip().lower()[:254]
    return email if _EMAIL_RE.match(email) else ""


def signup(email: str, name: str = "", source: str = "") -> dict:
    """Create/reuse a pending subscriber and return its confirmation token."""
    value = _valid_email(email)
    if not value:
        return {"ok": False, "error": "valid email required"}
    now = time.time()
    with _connection() as conn:
        row = conn.execute("SELECT * FROM subscribers WHERE email = ?", (value,)).fetchone()
        if row and row["status"] == "confirmed":
            return {"ok": True, "status": "confirmed", "token": row["token"], "email": value}
        token = row["token"] if row else secrets.token_urlsafe(28)
        if row:
            conn.execute(
                "UPDATE subscribers SET name=?, source=?, status='pending', unsubscribed_at=NULL WHERE email=?",
                (str(name or "").strip()[:120], str(source or "").strip()[:80], value),
            )
        else:
            conn.execute(
                "INSERT INTO subscribers (email, name, status, token, source, created_at) VALUES (?,?,?,?,?,?)",
                (value, str(name or "").strip()[:120], "pending", token, str(source or "").strip()[:80], now),
            )
        conn.commit()
    return {"ok": True, "status": "pending", "token": token, "email": value}


def confirm(token: str) -> dict | None:
    token = str(token or "").strip()
    if not token:
        return None
    now = time.time()
    with _connection() as conn:
        row = conn.execute("SELECT * FROM subscribers WHERE token = ?", (token,)).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE subscribers SET status='confirmed', confirmed_at=COALESCE(confirmed_at, ?), unsubscribed_at=NULL WHERE token=?",
            (now, token),
        )
        conn.commit()
        data = dict(row)
        data["status"] = "confirmed"
    add_brevo_contact(data["email"], data.get("name", ""))
    return data


def unsubscribe(token: str) -> dict | None:
    token = str(token or "").strip()
    if not token:
        return None
    with _connection() as conn:
        row = conn.execute("SELECT * FROM subscribers WHERE token = ?", (token,)).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE subscribers SET status='unsubscribed', unsubscribed_at=? WHERE token=?",
            (time.time(), token),
        )
        conn.commit()
        data = dict(row)
        data["status"] = "unsubscribed"
    remove_brevo_contact(data["email"])
    return data


def counts() -> dict:
    with _connection() as conn:
        rows = conn.execute("SELECT status, COUNT(*) AS n FROM subscribers GROUP BY status").fetchall()
    out = {"pending": 0, "confirmed": 0, "unsubscribed": 0}
    for row in rows:
        out[row["status"]] = int(row["n"])
    out["total"] = sum(out.values())
    return out


def list_confirmed() -> list[dict]:
    with _connection() as conn:
        rows = conn.execute("SELECT * FROM subscribers WHERE status='confirmed' ORDER BY confirmed_at").fetchall()
    return [dict(r) for r in rows]


def _brevo(method: str, path: str, payload: dict | None = None):
    if not BREVO_API_KEY:
        return 0, {"error": "BREVO_API_KEY is not configured"}
    try:
        response = requests.request(
            method,
            f"https://api.brevo.com/v3{path}",
            headers={"api-key": BREVO_API_KEY, "accept": "application/json", "content-type": "application/json"},
            json=payload,
            timeout=20,
        )
        try:
            data = response.json()
        except ValueError:
            data = {"text": response.text[:300]}
        return response.status_code, data
    except requests.RequestException as exc:
        logger.warning("Brevo request failed: %s", type(exc).__name__)
        return 0, {"error": "network"}


def add_brevo_contact(email: str, name: str = "") -> bool:
    if not configured():
        return False
    status, _ = _brevo(
        "POST",
        "/contacts",
        {
            "email": email,
            "attributes": {"FIRSTNAME": name or ""},
            "listIds": [BREVO_LIST_ID],
            "updateEnabled": True,
        },
    )
    return status in (200, 201, 204)


def remove_brevo_contact(email: str) -> bool:
    if not configured():
        return False
    status, _ = _brevo(
        "POST",
        f"/contacts/lists/{BREVO_LIST_ID}/contacts/remove",
        {"emails": [email]},
    )
    return status in (200, 201, 204)


def _send_email(to_email: str, subject: str, html_body: str, text_body: str, unsubscribe_url: str = "") -> bool:
    if not BREVO_API_KEY:
        return False
    payload = {
        "sender": {"name": NEWSLETTER_FROM_NAME, "email": NEWSLETTER_FROM_EMAIL},
        "replyTo": {"email": NEWSLETTER_REPLY_TO},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_body,
        "textContent": text_body,
    }
    if unsubscribe_url:
        payload["headers"] = {
            "List-Unsubscribe": f"<{unsubscribe_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }
    status, data = _brevo("POST", "/smtp/email", payload)
    if status not in (200, 201, 202):
        logger.warning("Brevo send failed status=%s", status)
        return False
    return True


def _layout(title: str, body: str, unsubscribe_url: str) -> str:
    return f"""<!doctype html><html><body style="margin:0;background:#f5f5f7;font-family:-apple-system,Segoe UI,sans-serif;color:#1d1d1f">
<div style="max-width:560px;margin:0 auto;padding:28px 20px">
  <div style="display:flex;align-items:center;gap:9px">
    <img src="{SITE_URL}/static/logo-signal-horizon.png" width="28" height="28" alt="Sightline"
         style="display:block;width:28px;height:28px;border-radius:6px;object-fit:contain">
    <div>
      <div style="font-size:20px;font-weight:800;letter-spacing:-.03em;line-height:1">Sightline</div>
      <div style="font-size:9px;letter-spacing:.12em;text-transform:uppercase;color:#8a8a91;margin-top:4px">Humanitarian intelligence</div>
    </div>
  </div>
  <div style="margin-top:18px;background:#fff;border:1px solid #e5e7eb;border-radius:16px;padding:24px">
    <h1 style="font-size:24px;line-height:1.2;margin:0 0 14px">{html.escape(title)}</h1>
    {body}
  </div>
  <p style="color:#94a3b8;font-size:11px;line-height:1.5;margin:16px 0 0">
    You receive this because you confirmed a subscription to Sightline.
    <a href="{html.escape(unsubscribe_url)}" style="color:#64748b">Unsubscribe</a>.
  </p>
</div></body></html>"""


def send_confirmation(token: str, email: str, name: str = "") -> bool:
    link = f"{SITE_URL}/newsletter/confirm/{token}"
    unsub = f"{SITE_URL}/newsletter/unsubscribe/{token}"
    body = (
        "<p style='color:#475569;line-height:1.6;margin:0 0 16px'>Confirm your email to receive the weekly "
        "humanitarian signal: crisis data, SITREPs and donor workflows in one short note.</p>"
        f"<p style='margin:0 0 20px'><a href='{html.escape(link)}' "
        "style='display:inline-block;background:#0ea5e9;color:#fff;text-decoration:none;font-weight:700;"
        "padding:11px 16px;border-radius:9px'>Confirm subscription</a></p>"
        "<p style='color:#94a3b8;font-size:12px;margin:0'>If you did not request this, ignore this email.</p>"
    )
    return _send_email(
        email,
        "Confirm your Sightline subscription",
        _layout("One click to confirm", body, unsub),
        f"Confirm your Sightline subscription: {link}",
        unsub,
    )


def _clean_rich(value: str) -> str:
    """Escape and lightly render the small Markdown subset used in bulletins."""
    text = html.escape(str(value or "").strip())
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text, flags=re.S)
    text = re.sub(r"^\s*#+\s*", "", text, flags=re.M)
    parts = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    return "".join(
        f"<p style='color:#475569;font-size:14px;line-height:1.65;margin:0 0 12px'>{part.replace(chr(10), ' ')}</p>"
        for part in parts
    )


def _latest_bulletin() -> dict | None:
    from sitrep.weekly_bulletin import BULLETINS_DIR

    files = sorted(BULLETINS_DIR.glob("*_bulletin.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None
    try:
        data = json.loads(files[0].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    label = str(data.get("week_label") or files[0].stem)
    slug = files[0].stem.replace("_bulletin", "").lower()
    return {
        "label": label,
        "overview": str(data.get("global_overview") or ""),
        "url": f"{SITE_URL}/bulletin/{slug}",
        "subject": "What changed in humanitarian aid this week",
        "figures": data.get("key_figures") or [],
        "themes": data.get("top_themes") or [],
        "crises": data.get("crises") or [],
        "total_reports": data.get("total_reports") or 0,
        "countries": data.get("countries_affected") or 0,
        "active_crises": len(data.get("crises") or []),
    }


def _bulletin_email(data: dict, unsubscribe_url: str, *, welcome: bool = False) -> tuple[str, str, str]:
    label = html.escape(str(data.get("label") or ""))
    subject = "You're in — what changed this week" if welcome else "What changed in humanitarian aid this week"
    intro = (
        "<p style='color:#0284c7;font-size:11px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;margin:0 0 8px'>"
        "Weekly humanitarian briefing</p>"
        f"<p style='color:#8a8a91;font-size:12px;margin:0 0 18px'>{label}</p>"
    )
    if welcome:
        intro = (
            "<p style='color:#0284c7;font-size:11px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;margin:0 0 8px'>"
            "You are in</p>"
            "<p style='color:#475569;font-size:14px;line-height:1.6;margin:0 0 18px'>Thanks for confirming your subscription. "
            "Here is the latest weekly briefing — no noise, just what changed.</p>"
            f"<p style='color:#8a8a91;font-size:12px;margin:0 0 18px'>{label}</p>"
        )
    overview = _clean_rich(data.get("overview") or "")
    figures = data.get("figures") or []
    figure_cells = ""
    for item in figures[:6]:
        figure_cells += (
            "<td style='padding:8px 6px;vertical-align:top;width:33.33%'>"
            f"<div style='color:#0f172a;font-size:19px;font-weight:800;letter-spacing:-.02em'>{html.escape(str(item.get('value') or '—'))}</div>"
            f"<div style='color:#8a8a91;font-size:10px;line-height:1.3'>{html.escape(str(item.get('label') or ''))}</div>"
            "</td>"
        )
    figures_html = ""
    if figure_cells:
        figures_html = (
            "<div style='margin:0 0 20px;padding:12px 6px;border:1px solid #e5e7eb;border-radius:12px;background:#f8fafc'>"
            f"<table role='presentation' width='100%' cellpadding='0' cellspacing='0'>{figure_cells}</table></div>"
        )
    crises = data.get("crises") or []
    severity_rank = {"high": 3, "medium": 2, "low": 1}
    crises = sorted(
        crises, key=lambda c: (severity_rank.get(str(c.get("severity")), 0), c.get("report_count") or 0), reverse=True
    )[:4]
    crisis_html = ""
    for crisis in crises:
        country = html.escape(str(crisis.get("country") or ""))
        headline = html.escape(str(crisis.get("headline") or ""))
        summary = html.escape(str(crisis.get("summary") or ""))[:360]
        severity = str(crisis.get("severity") or "").lower()
        color = {"high": "#dc2626", "medium": "#d97706"}.get(severity, "#0284c7")
        crisis_html += (
            "<div style='padding:14px 0;border-top:1px solid #e5e7eb'>"
            f"<div style='color:{color};font-size:10px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;margin-bottom:4px'>{country}</div>"
            f"<div style='color:#0f172a;font-size:15px;font-weight:750;line-height:1.3;margin-bottom:5px'>{headline}</div>"
            f"<div style='color:#475569;font-size:12.5px;line-height:1.55'>{summary}{'…' if len(str(crisis.get('summary') or '')) > 360 else ''}</div>"
            "</div>"
        )
    themes = data.get("themes") or []
    theme_html = "".join(
        f"<span style='display:inline-block;margin:0 4px 5px 0;padding:4px 8px;border-radius:999px;background:#f1f5f9;color:#475569;font-size:10px'>{html.escape(str(t))}</span>"
        for t in themes[:6]
    )
    cta = (
        f"<p style='margin:20px 0 0'><a href='{html.escape(data['url'])}' "
        "style='display:inline-block;background:#0f172a;color:#fff;text-decoration:none;font-weight:700;"
        "padding:11px 15px;border-radius:9px;font-size:13px'>Read the full weekly briefing →</a></p>"
    )
    app_url = f"{SITE_URL}/app?utm_source=newsletter&utm_medium=email&utm_campaign=weekly"
    promo = (
        "<div style='margin:26px 0 0;padding:16px;border-radius:12px;background:#0f172a;color:#ffffff'>"
        "<div style='color:#7dd3fc;font-size:9px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;margin-bottom:6px'>Sightline workspace</div>"
        "<div style='font-size:17px;font-weight:750;line-height:1.2;margin-bottom:6px'>Put this brief to work.</div>"
        "<p style='color:#cbd5e1;font-size:12px;line-height:1.5;margin:0 0 12px'>Ask a follow-up, generate a cited SITREP, or start a donor proposal. The guest chat is free — no account needed for the first three messages.</p>"
        f"<a href='{html.escape(app_url, quote=True)}' style='display:inline-block;background:#7dd3fc;color:#082f49;text-decoration:none;font-weight:800;padding:9px 13px;border-radius:8px;font-size:12px'>Open Sightline →</a>"
        "</div>"
    )
    body = (
        f"{intro}"
        f"<div style='font-size:15px;line-height:1.65'>{overview}</div>"
        f"{figures_html}"
        f"<p style='color:#8a8a91;font-size:10px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;margin:0 0 2px'>Crises to watch</p>"
        f"{crisis_html}"
        f"{'<p style="color:#8a8a91;font-size:10px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;margin:16px 0 4px">Themes</p>' + theme_html if theme_html else ''}"
        f"{cta}{promo}"
    )
    text = f"{subject}\n{data.get('label')}\n\n{data.get('overview')}\n\nRead the full briefing: {data['url']}\n\nTry Sightline: {app_url}"
    return subject, _layout(subject, body, unsubscribe_url), text


def _bulletin_content() -> tuple[str, str, str] | None:
    data = _latest_bulletin()
    if not data:
        return None
    return _bulletin_email(data, "{{unsubscribe}}")


def _sitrep_content() -> tuple[str, str, str] | None:
    from config import OUTPUT_REPORTS_DIR

    files = sorted(OUTPUT_REPORTS_DIR.glob("*_report.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None
    try:
        data = json.loads(files[0].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    title = str(data.get("title") or files[0].stem.replace("_report", "").replace("_", " "))
    summary = html.escape(str(data.get("summary") or ""))[:1200]
    url = f"{SITE_URL}/sitreps"
    subject = f"New SITREP: {title}"
    body = (
        f"<p style='color:#475569;line-height:1.65;margin:0 0 18px'>{summary}</p>"
        f"<p style='margin:0 0 18px'><a href='{url}' style='color:#0284c7;font-weight:700'>Open the report archive →</a></p>"
    )
    return subject, _layout(subject, body, "{{unsubscribe}}"), f"{subject}\n{url}"


def send_welcome(email: str, token: str, name: str = "") -> bool:
    """Thank-you email that also carries the full latest bulletin."""
    data = _latest_bulletin()
    unsub = f"{SITE_URL}/newsletter/unsubscribe/{token}"
    if not data:
        title = "You're in — welcome to Sightline"
        body = "<p style='color:#475569'>Thanks for confirming your subscription. Your first briefing will arrive soon.</p>"
        return _send_email(email, title, _layout(title, body, unsub), title, unsub)
    subject, html_body, text_body = _bulletin_email(data, unsub, welcome=True)
    return _send_email(email, subject, html_body, text_body, unsub)


def send_bulletin_preview(to_email: str) -> bool:
    data = _latest_bulletin()
    if not data:
        return send_test(to_email)
    unsub = f"{SITE_URL}/newsletter/unsubscribe/preview"
    subject, html_body, text_body = _bulletin_email(data, unsub)
    return _send_email(to_email, subject, html_body, text_body, unsub)


def send_broadcast(kind: str = "bulletin") -> dict:
    """Send the latest bulletin/SITREP to confirmed subscribers (transactional)."""
    content = _bulletin_content() if kind != "sitrep" else _sitrep_content()
    if not content:
        return {"ok": False, "error": "No content available"}
    subject, html_template, text_template = content
    sent = failed = 0
    if not configured():
        return {"ok": False, "error": "Newsletter is not configured"}
    for subscriber in list_confirmed():
        unsubscribe_url = f"{SITE_URL}/newsletter/unsubscribe/{subscriber['token']}"
        html_body = html_template.replace("{{unsubscribe}}", unsubscribe_url)
        text_body = text_template + f"\n\nUnsubscribe: {unsubscribe_url}"
        if _send_email(subscriber["email"], subject, html_body, text_body, unsubscribe_url):
            sent += 1
        else:
            failed += 1
    return {"ok": True, "sent": sent, "failed": failed, "subject": subject}


def send_test(to_email: str) -> bool:
    return send_bulletin_preview(to_email)
