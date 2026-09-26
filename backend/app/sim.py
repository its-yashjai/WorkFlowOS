"""Demo data: customers, inbox, chat history and a simulated week of observed work."""
import json
import random
from datetime import datetime, timedelta

from . import apps, db

CUSTOMERS = [
    ("Priya Nair", "priya@brightnet.io", "Brightnet", "Enterprise"),
    ("Rahul Mehta", "rahul@acmecorp.in", "Acme Corp", "Growth"),
    ("Arjun Rao", "arjun@zentro.co", "Zentro", "Enterprise"),
    ("Sneha Iyer", "sneha@lumenlabs.ai", "Lumen Labs", "Standard"),
    ("Kabir Shah", "kabir@finlyte.com", "Finlyte", "Growth"),
    ("Meera Pillai", "meera@orbitmart.in", "OrbitMart", "Standard"),
]
PAST = [  # (customer index, subject, attachment, body)
    (1, "Updated billing address for Q4", "Billing_Address_Q4.pdf", "Please update our billing address, new details attached."),
    (0, "Purchase order PO-4471", "PO-4471.pdf", "Attaching PO-4471 for the 20 additional seats."),
    (4, "Signed data processing agreement", "DPA_signed.pdf", "Here's the signed DPA for your records."),
    (2, "Tax exemption certificate", "Tax_Exemption_2026.pdf", "Our tax exemption certificate for this year."),
]
NEW = [  # emails waiting in the inbox for the live demo
    (3, "Invoice correction request", "Invoice_1182_correction.pdf", "Invoice 1182 has the wrong GST number, corrected copy attached."),
    (5, "Vendor registration form", "Vendor_Form_OrbitMart.pdf", "Filled vendor registration form attached, please update our account."),
]
TEST_EMAILS = [
    ("Kabir Shah", "kabir@finlyte.com", "Updated W-9 form", "W9_Finlyte_2026.pdf", "Attaching our updated W-9 form."),
    ("Nisha Verma", "nisha@finlyte.com", "New billing contact", "Billing_Contact.pdf", "I'm the new billing contact for Finlyte, details attached."),
    ("Meera Pillai", "meera@orbitmart.in", "Revised purchase order", "PO-5520_revised.pdf", "Revised PO attached with updated quantities."),
    ("Rahul Mehta", "rahul@acmecorp.in", "Invoice for September", "Invoice_INV-2291.pdf", "Please find our September invoice attached."),
]


def note_for(subject, attachment):
    return f"Customer request: {subject} (see {attachment})"


def msg_for(name, company, subject):
    return f"New request from {name} ({company}): {subject}. Logged in CRM ✅"


def seed():
    db.reset()
    for c in CUSTOMERS:
        apps.create_customer(*c)
    now = datetime.now()
    for i, (ci, subj, att, body) in enumerate(PAST):
        n, e, co, _ = CUSTOMERS[ci]
        apps.receive_email(n, e, subj, body, att, ts=(now - timedelta(days=6 - i, hours=3)).isoformat(timespec="seconds"))
    for ci, subj, att, body in NEW:
        n, e, co, _ = CUSTOMERS[ci]
        apps.receive_email(n, e, subj, body, att, ts=(now - timedelta(minutes=40 - ci)).isoformat(timespec="seconds"))
    apps.receive_email("Team Lunch Bot", "noreply@lunch.app", "Friday lunch poll", "Vote for Friday lunch!", "",
                       ts=(now - timedelta(hours=5)).isoformat(timespec="seconds"))
    for ch, a, t in [("#general", "Anita", "Morning all! Standup in 10."), ("#sales", "Vikram", "Closed Zentro expansion 🎉")]:
        db.ex("INSERT INTO chat(channel,author,text,ts) VALUES (?,?,?,?)", (ch, a, t, (now - timedelta(hours=6)).isoformat(timespec="seconds")))
    simulate_week()


def _ev(t, app, action, data, target=""):
    db.ex("INSERT INTO events(ts, source, app, action, target, data) VALUES (?,?,?,?,?,?)",
          (t.isoformat(timespec="seconds"), "sim", app, action, target, json.dumps(data)))


def simulate_week():
    """What the agent would have recorded over the last week: the same customer-request
    routine four times, plus unrelated work (spreadsheets, browsing) as noise."""
    rnd = random.Random(7)
    now = datetime.now()
    emails = db.q("SELECT * FROM emails ORDER BY id")
    custs = {c["email"]: c for c in db.q("SELECT * FROM customers")}
    for i, (ci, subj, att, body) in enumerate(PAST):
        e = emails[i]
        c = custs[e["sender_email"]]
        t = now - timedelta(days=6 - i, hours=2, minutes=rnd.randint(0, 40))
        step = lambda s: t + timedelta(seconds=s)  # noqa: E731
        _ev(step(0), "desktop", "app_focus", {"process": "chrome.exe", "title": "Mailbox"})
        _ev(step(5), "mail", "open_email", {"email_id": e["id"], "from_email": e["sender_email"], "from_name": e["sender_name"],
                                            "subject": subj, "attachment": att}, subj)
        _ev(step(48), "mail", "download_attachment", {"email_id": e["id"], "filename": att}, att)
        _ev(step(52), "files", "file_saved", {"filename": att, "folder": "Downloads"}, att)
        _ev(step(95 + rnd.randint(0, 40)), "crm", "search", {"query": e["sender_email"].split("@")[1].split(".")[0]})
        _ev(step(120 + rnd.randint(0, 40)), "crm", "open_record", {"customer_id": c["id"], "email": c["email"],
                                                                  "company": c["company"], "name": c["name"]}, c["name"])
        _ev(step(260 + rnd.randint(0, 60)), "crm", "update_record", {"customer_id": c["id"], "note": note_for(subj, att),
                                                                    "attachment": att, "company": c["company"]}, c["name"])
        _ev(step(300 + rnd.randint(0, 60)), "chat", "open_channel", {"channel": "#support"}, "#support")
        _ev(step(345 + rnd.randint(0, 60)), "chat", "post_message", {"channel": "#support",
                                                                    "text": msg_for(c["name"], c["company"], subj)}, "#support")
        db.ex("UPDATE emails SET read=1, handled_by=0 WHERE id=?", (e["id"],))  # you handled these by hand
        db.ex("INSERT INTO chat(channel,author,text,ts) VALUES (?,?,?,?)",
              ("#support", db.settings().get("user_name", "You"), msg_for(c["name"], c["company"], subj),
               step(350).isoformat(timespec="seconds")))
        notes = json.loads(db.one("SELECT notes FROM customers WHERE id=?", (c["id"],))["notes"])
        notes.insert(0, {"text": note_for(subj, att), "ts": step(260).isoformat(timespec="seconds"), "by": "You", "attachment": att})
        db.ex("UPDATE customers SET notes=?, files=? WHERE id=?", (json.dumps(notes), json.dumps([att]), c["id"]))
    # noise: unrelated work between routines
    for d in range(6):
        t = now - timedelta(days=d, hours=6)
        _ev(t, "desktop", "app_focus", {"process": "EXCEL.EXE", "title": "Weekly_numbers.xlsx - Excel"})
        _ev(t + timedelta(minutes=12), "desktop", "app_focus", {"process": "chrome.exe", "title": "Docs"})
        _ev(t + timedelta(minutes=14), "web", "navigate", {"domain": "news.ycombinator.com", "title": "Hacker News"})
        if d % 3 == 0:
            _ev(t + timedelta(minutes=30), "desktop", "app_focus", {"process": "WINWORD.EXE", "title": "Proposal.docx - Word"})


def test_email(i: int = 0):
    n, e, s, a, b = TEST_EMAILS[i % len(TEST_EMAILS)]
    return apps.receive_email(n, e, s, b, a)
