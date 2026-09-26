import os
"""Demo apps (Mailbox, Ledger CRM, Huddle) as a service layer.

Actions done by a person are recorded as structured events (like an accessibility /
semantic UI observer would). Actions done by the automation engine are not, so
WorkFlowOS never "learns" from its own runs.
"""
import json

from . import db


def emit(app, action, data, source="observer", target=""):
    if db.settings().get("observing") != "1":
        return None
    return db.ex("INSERT INTO events(ts, source, app, action, target, data) VALUES (?,?,?,?,?,?)",
                 (db.now(), source, app, action, target, json.dumps(data)))


# ---------------- Mailbox ----------------
def list_emails():
    return db.q("SELECT * FROM emails ORDER BY received_at DESC, id DESC")


def get_email(eid: int, actor="user"):
    e = db.one("SELECT * FROM emails WHERE id=?", (eid,))
    if not e:
        return None
    db.ex("UPDATE emails SET read=1 WHERE id=?", (eid,))
    if actor == "user":
        emit("mail", "open_email", {"email_id": eid, "from_email": e["sender_email"], "from_name": e["sender_name"],
                                    "subject": e["subject"], "attachment": e["attachment"]}, target=e["subject"])
    return e


def download_attachment(eid: int, actor="user"):
    e = db.one("SELECT * FROM emails WHERE id=?", (eid,))
    if not e or not e["attachment"]:
        return None
    if actor == "user":
        emit("mail", "download_attachment", {"email_id": eid, "filename": e["attachment"]}, target=e["attachment"])
    if e.get("file") and os.path.isfile(e["file"]):  # a real attachment from Gmail
        with open(e["file"], "rb") as f:
            return e["attachment"], f.read()
    return e["attachment"], make_pdf(f"{e['attachment']}", f"From {e['sender_name']} <{e['sender_email']}>", e["subject"], e["body"] or "")


def receive_email(sender_name, sender_email, subject, body, attachment="", ts=None):
    return db.ex("INSERT INTO emails(sender_name,sender_email,subject,body,attachment,received_at) VALUES (?,?,?,?,?,?)",
                 (sender_name, sender_email, subject, body, attachment, ts or db.now()))


# ---------------- Ledger CRM ----------------
def _cust(c):
    if not c:
        return None
    c = dict(c)
    c["notes"] = db.js(c["notes"], [])
    c["files"] = db.js(c["files"], [])
    return c


def search_customers(query="", actor="user"):
    rows = db.q("SELECT * FROM customers ORDER BY name")
    if query:
        ql = query.lower()
        rows = [r for r in rows if ql in (r["name"] + " " + r["email"] + " " + r["company"]).lower()]
        if actor == "user":
            emit("crm", "search", {"query": query, "results": len(rows)}, target=query)
    return [_cust(r) for r in rows]


def get_customer(cid: int, actor="user"):
    c = _cust(db.one("SELECT * FROM customers WHERE id=?", (cid,)))
    if c and actor == "user":
        emit("crm", "open_record", {"customer_id": cid, "email": c["email"], "company": c["company"], "name": c["name"]},
             target=c["name"])
    return c


def find_by_email(email: str):
    return _cust(db.one("SELECT * FROM customers WHERE lower(email)=lower(?)", (email or "",)))


def find_by_domain(email: str):
    dom = (email or "").split("@")[-1].lower()
    if not dom or dom in ("gmail.com", "yahoo.com", "outlook.com", "hotmail.com"):
        return None
    for c in db.q("SELECT * FROM customers"):
        if c["email"].lower().endswith("@" + dom):
            return _cust(c)
    return None


def update_customer(cid: int, note: str, attachment: str = "", actor="user"):
    c = _cust(db.one("SELECT * FROM customers WHERE id=?", (cid,)))
    if not c:
        return None
    by = "WorkFlowOS" if actor != "user" else db.settings().get("user_name", "You")
    c["notes"].insert(0, {"text": note, "ts": db.now(), "by": by, "attachment": attachment})
    if attachment and attachment not in c["files"]:
        c["files"].insert(0, attachment)
    db.ex("UPDATE customers SET notes=?, files=?, updated_at=? WHERE id=?",
          (json.dumps(c["notes"]), json.dumps(c["files"]), db.now(), cid))
    if actor == "user":
        emit("crm", "update_record", {"customer_id": cid, "note": note, "attachment": attachment, "company": c["company"]},
             target=c["name"])
    return c


def remove_note(cid: int, text: str, attachment: str = "") -> bool:
    c = _cust(db.one("SELECT * FROM customers WHERE id=?", (cid,)))
    if not c:
        return False
    idx = next((i for i, n in enumerate(c["notes"]) if n["text"] == text and n.get("by") == "WorkFlowOS"), None)
    if idx is None:
        return False
    c["notes"].pop(idx)
    if attachment and not any(n.get("attachment") == attachment for n in c["notes"]):
        c["files"] = [f for f in c["files"] if f != attachment]
    db.ex("UPDATE customers SET notes=?, files=?, updated_at=? WHERE id=?",
          (json.dumps(c["notes"]), json.dumps(c["files"]), db.now(), cid))
    return True


def delete_chat(channel: str, text: str) -> bool:
    m = db.one("SELECT id FROM chat WHERE channel=? AND text=? AND bot=1 ORDER BY id DESC LIMIT 1", (channel, text))
    if m:
        db.ex("DELETE FROM chat WHERE id=?", (m["id"],))
    return bool(m)


def create_customer(name, email, company, tier="Standard"):
    return db.ex("INSERT INTO customers(name,email,company,tier,updated_at) VALUES (?,?,?,?,?)",
                 (name, email, company, tier, db.now()))


# ---------------- Huddle chat ----------------
def list_chat(channel: str):
    return db.q("SELECT * FROM chat WHERE channel=? ORDER BY ts, id", (channel,))


def channels():
    rows = db.q("SELECT channel, COUNT(*) n, MAX(ts) last FROM chat GROUP BY channel ORDER BY channel")
    names = {r["channel"] for r in rows}
    for c in ("#support", "#sales", "#general"):
        if c not in names:
            rows.append({"channel": c, "n": 0, "last": None})
    return sorted(rows, key=lambda r: r["channel"])


def post_chat(channel: str, text: str, actor="user", ts=None):
    author = "WorkFlowOS" if actor != "user" else db.settings().get("user_name", "You")
    mid = db.ex("INSERT INTO chat(channel,author,text,ts,bot) VALUES (?,?,?,?,?)",
                (channel, author, text, ts or db.now(), 0 if actor == "user" else 1))
    if actor == "user":
        emit("chat", "post_message", {"channel": channel, "text": text}, target=channel)
    return mid


# ---------------- tiny valid PDF for attachments ----------------
def make_pdf(*lines: str) -> bytes:
    safe = [l.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")[:90] for l in lines]
    text = "BT /F1 13 Tf 50 780 Td " + " ".join(f"({l}) Tj 0 -22 Td" for l in safe) + " ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(text)} >>\nstream\n{text}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offs = "%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out.encode("latin-1", "replace")))
        out += f"{i} 0 obj\n{o}\nendobj\n"
    xref = len(out.encode("latin-1", "replace"))
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF"
    return out.encode("latin-1", "replace")
