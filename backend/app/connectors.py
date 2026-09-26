"""Real app connectors: Gmail (in) and Slack (out).

Gmail: IMAP with a Google App Password (no Cloud project needed). WorkFlowOS only imports emails that
arrive AFTER you connect and that carry an attachment, opens the inbox read-only (nothing is marked read),
and keeps the real attachment file so the workflow processes the actual document.

Slack: an Incoming Webhook URL. The "notify the team" step posts there (API tier) and mirrors the message
into Huddle so the run page can show it. If Slack is unreachable, the engine falls back as usual.
"""
import email
import imaplib
import os
import re
from email.header import decode_header, make_header
from email.utils import parseaddr

import httpx

from . import apps, db

INBOX_DIR = os.path.join(os.path.dirname(__file__), "..", "files", "inbox")
STATUS = {"gmail": {"error": "", "checked": None, "imported": 0}, "slack": {"error": "", "sent": 0}}


# ---------------- Gmail ----------------
def gmail_creds():
    s = db.settings()
    return s.get("gmail_user", "").strip(), s.get("gmail_app_password", "").replace(" ", "").strip()


def gmail_enabled() -> bool:
    u, p = gmail_creds()
    return bool(u and p)


def _imap():
    u, p = gmail_creds()
    m = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=20)
    m.login(u, p)
    m.select("INBOX", readonly=True)  # read-only: WorkFlowOS never marks your mail as read
    return m


def _max_uid(m) -> int:
    typ, data = m.uid("search", None, "ALL")
    uids = [int(x) for x in (data[0] or b"").split()]
    return max(uids) if uids else 0


def gmail_connect() -> dict:
    """Log in once to check the password, and start from 'now' so old mail is never imported."""
    try:
        m = _imap()
        top = _max_uid(m)
        m.logout()
    except imaplib.IMAP4.error as e:
        STATUS["gmail"]["error"] = "Gmail refused the login. Use a 16-letter App Password, not your normal password."
        return {"ok": False, "message": STATUS["gmail"]["error"], "detail": str(e)[:200]}
    except Exception as e:  # noqa: BLE001
        STATUS["gmail"]["error"] = f"Couldn't reach Gmail: {str(e)[:120]}"
        return {"ok": False, "message": STATUS["gmail"]["error"]}
    db.set_setting("gmail_last_uid", str(top))
    STATUS["gmail"].update(error="", checked=db.now())
    return {"ok": True, "message": "Connected. New emails with attachments will appear in Mailbox."}


def _dec(v) -> str:
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:  # noqa: BLE001
        return v or ""


def _safe_name(n: str) -> str:
    n = re.sub(r"[^\w.\- ]", "_", n).strip() or "attachment"
    return n[:120]


def parse_message(raw: bytes) -> dict | None:
    """Sender, subject, text body and the first attachment of one email (None if it has no attachment)."""
    msg = email.message_from_bytes(raw)
    name, addr = parseaddr(_dec(msg.get("From")))
    body, att = "", None
    for part in msg.walk():
        if part.is_multipart():
            continue
        fn = part.get_filename()
        disp = (part.get("Content-Disposition") or "").lower()
        if fn or "attachment" in disp:
            if att is None:
                data = part.get_payload(decode=True) or b""
                if data:
                    att = (_safe_name(_dec(fn or "attachment")), data)
        elif part.get_content_type() == "text/plain" and not body:
            try:
                body = (part.get_payload(decode=True) or b"").decode(part.get_content_charset() or "utf-8", "replace")
            except Exception:  # noqa: BLE001
                body = ""
    if not att:
        return None
    return {"name": name or addr.split("@")[0], "email": addr.lower(), "subject": _dec(msg.get("Subject")) or "(no subject)",
            "body": body.strip()[:2000], "attachment": att}


def store(parsed: dict, uid) -> int:
    os.makedirs(INBOX_DIR, exist_ok=True)
    fname, data = parsed["attachment"]
    path = os.path.join(INBOX_DIR, f"{uid}_{fname}")
    with open(path, "wb") as f:
        f.write(data)
    eid = apps.receive_email(parsed["name"], parsed["email"], parsed["subject"], parsed["body"], fname)
    db.ex("UPDATE emails SET source='gmail', file=? WHERE id=?", (path, eid))
    return eid


def gmail_poll() -> list[int]:
    """Import new Gmail messages that have an attachment. Returns the new Mailbox email ids."""
    if not gmail_enabled():
        return []
    last = int(db.settings().get("gmail_last_uid") or 0)
    new = []
    m = _imap()
    try:
        typ, data = m.uid("search", None, f"UID {last + 1}:*")
        uids = sorted(u for u in (int(x) for x in (data[0] or b"").split()) if u > last)
        for uid in uids[-10:]:
            typ, parts = m.uid("fetch", str(uid), "(BODY.PEEK[])")
            raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
            parsed = parse_message(raw) if raw else None
            if parsed:
                new.append(store(parsed, uid))
        if uids:
            db.set_setting("gmail_last_uid", str(max(uids)))
    finally:
        try:
            m.logout()
        except Exception:  # noqa: BLE001
            pass
    STATUS["gmail"].update(error="", checked=db.now())
    STATUS["gmail"]["imported"] += len(new)
    return new


# ---------------- Slack ----------------
def slack_url() -> str:
    u = db.settings().get("slack_webhook", "").strip()
    return u if u.startswith("https://hooks.slack.com/") else ""


def slack_post(text: str):
    """Post to Slack. Raises on failure so the engine can fall back."""
    url = slack_url()
    if not url:
        raise RuntimeError("Slack isn't connected")
    r = httpx.post(url, json={"text": text}, timeout=8)
    if r.status_code != 200:
        STATUS["slack"]["error"] = f"Slack said {r.status_code}: {r.text[:80]}"
        raise RuntimeError(STATUS["slack"]["error"])
    STATUS["slack"]["error"] = ""
    STATUS["slack"]["sent"] += 1


def slack_connect() -> dict:
    if not slack_url():
        return {"ok": False, "message": "That doesn't look like a Slack webhook (it starts with https://hooks.slack.com/)."}
    try:
        slack_post("✅ WorkFlowOS is connected. Automated team notifications will appear here.")
        return {"ok": True, "message": "Connected. Check Slack for the test message."}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": f"Couldn't post to Slack: {str(e)[:120]}"}


def status() -> dict:
    u, _ = gmail_creds()
    return {"gmail": {"connected": gmail_enabled(), "user": u, **STATUS["gmail"]},
            "slack": {"connected": bool(slack_url()), **STATUS["slack"]}}
