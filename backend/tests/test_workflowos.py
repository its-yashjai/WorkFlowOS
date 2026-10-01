"""Core behaviour: discovery, generation, tiered automation, human-in-the-loop, learning.
Run:  cd backend && python -m pytest -q
"""
import asyncio
import json
import os
import tempfile
from datetime import datetime, timedelta

os.environ["WFOS_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

import pytest  # noqa: E402

from app import apps, db, discovery, engine, llm, sim  # noqa: E402

llm._ollama.update(checked=1e18, model=None)  # tests never use a local model: deterministic rules


@pytest.fixture(autouse=True)
def fresh():
    sim.seed()
    db.set_setting("api_outage", "1")  # no server in tests: API tier fails, app integration takes over
    yield


def run(coro):
    return asyncio.run(coro)


def active_workflow():
    discovery.refresh()
    w = db.one("SELECT * FROM workflows WHERE name='Process customer request'")
    db.ex("UPDATE workflows SET status='active' WHERE id=?", (w["id"],))
    return w


def start_for(w, email_i):
    eid = sim.test_email(email_i)
    e = db.one("SELECT * FROM emails WHERE id=?", (eid,))
    return engine.start(w["id"], {"type": "new_email", "email_id": eid, "subject": e["subject"], "from": e["sender_name"]})


def test_discovers_the_repeated_routine_and_ignores_noise():
    pats = discovery.mine()
    top = pats[0]
    assert top["support"] == 4
    assert top["steps"][0] == "mail.open_email" and "chat.post_message" in top["steps"]
    assert top["switches"] >= 2


def test_generated_workflow_has_trigger_condition_and_templates():
    w = active_workflow()
    spec = json.loads(w["spec"])
    assert spec["trigger"]["type"] == "new_email"
    actions = [s["action"] for s in spec["steps"]]
    assert actions == ["read_email", "download_attachment", "find_customer", "update_customer", "send_message"]
    assert any(c["if"] == "customer_not_found" for c in spec["conditions"])
    msg = next(s for s in spec["steps"] if s["action"] == "send_message")["params"]["text"]
    assert "{{" in msg  # user's typed messages became a template


def test_run_falls_back_from_api_to_app_integration():
    w = active_workflow()
    rid = start_for(w, 0)
    run(engine.execute(rid))
    r = engine._load(rid)
    assert r["status"] == "done"
    for s in r["steps"]:
        assert [t["tier"] for t in s["tried"]] == ["api", "app"]
        assert s["tried"][0]["ok"] is False and s["tried"][1]["ok"] is True
    kabir = apps.find_by_email("kabir@finlyte.com")
    assert any("W-9" in n["text"] or "W9" in (n.get("attachment") or "") for n in kabir["notes"])


def test_unknown_customer_stops_and_asks_then_learns():
    w = active_workflow()
    rid = start_for(w, 1)  # sender not in CRM, same domain as an existing customer
    run(engine.execute(rid))
    r = engine._load(rid)
    assert r["status"] == "needs_you"
    note = json.loads(r["note"])
    assert note["suggested"] and "Kabir" in note["suggested_name"]
    run(engine.resolve(rid, customer_id=note["suggested"], remember=True))
    assert engine._load(rid)["status"] == "done"
    # same sender again: handled automatically from what it learned
    rid2 = start_for(w, 1)
    run(engine.execute(rid2))
    r2 = engine._load(rid2)
    assert r2["status"] == "done"
    assert next(s for s in r2["steps"] if s["id"] == "find")["tier"] == "learned"


def test_automation_is_not_observed_as_user_activity():
    w = active_workflow()
    before = db.one("SELECT COUNT(*) n FROM events")["n"]
    rid = start_for(w, 0)
    run(engine.execute(rid))
    assert db.one("SELECT COUNT(*) n FROM events")["n"] == before


def _web_routine(days=3):
    base = datetime.now() - timedelta(days=days)
    o = "http://127.0.0.1:9"
    for d in range(days):
        t = base + timedelta(days=d)
        for dt, (app, action, data) in enumerate([
            ("web", "navigate", {"domain": "portal.test", "origin": o, "path": "/", "title": "Portal"}),
            ("web", "click", {"domain": "portal.test", "origin": o, "path": "/", "text": "Download report"}),
            ("desktop", "app_focus", {"process": "EXCEL.EXE", "title": "report - Excel"}),
        ]):
            db.ex("INSERT INTO events(ts,source,app,action,target,data) VALUES (?,?,?,?,?,?)",
                  ((t + timedelta(seconds=dt * 30)).isoformat(timespec="seconds"), "extension", app, action, "", json.dumps(data)))


def test_real_world_web_and_desktop_routine_becomes_runnable_steps():
    _web_routine()
    discovery.refresh()
    w = db.one("SELECT * FROM workflows WHERE name LIKE 'Routine:%'")
    assert w, "web + desktop routine should be suggested"
    spec = json.loads(w["spec"])
    assert [s["action"] for s in spec["steps"]] == ["open_page", "click", "manual"]
    assert spec["steps"][1]["label"] == 'Click "Download report" on portal.test'
    assert spec["trigger"]["type"] == "manual"


def test_manual_step_pauses_and_continues():
    _web_routine()
    discovery.refresh()
    w = db.one("SELECT * FROM workflows WHERE name LIKE 'Routine:%'")
    spec = json.loads(w["spec"])
    spec["steps"] = [s for s in spec["steps"] if s["action"] == "manual"]  # skip real browser in tests
    db.ex("UPDATE workflows SET spec=? WHERE id=?", (json.dumps(spec), w["id"]))
    rid = engine.start(w["id"], {"type": "manual", "subject": w["name"], "from": "you"})
    run(engine.execute(rid))
    r = engine._load(rid)
    assert r["status"] == "needs_you" and json.loads(r["note"])["kind"] == "manual"
    run(engine.resolve(rid))
    assert engine._load(rid)["status"] == "done"


def test_new_workflow_previews_changes_before_making_them_and_earns_autopilot():
    w = active_workflow()
    learned = json.loads(db.one("SELECT learned FROM workflows WHERE id=?", (w["id"],))["learned"])
    learned["mode"] = "preview"
    db.ex("UPDATE workflows SET learned=? WHERE id=?", (json.dumps(learned), w["id"]))
    for n in range(2):
        rid = start_for(w, 0)
        run(engine.execute(rid))
        r = engine._load(rid)
        note = json.loads(r["note"])
        assert r["status"] == "needs_you" and note["kind"] == "preview"
        assert {c["app"] for c in note["changes"]} == {"crm", "chat"}
        before = len(apps.find_by_email("kabir@finlyte.com")["notes"])
        run(engine.resolve(rid))  # approve unchanged
        assert engine._load(rid)["status"] == "done"
        assert len(apps.find_by_email("kabir@finlyte.com")["notes"]) == before + 1
    wf = db.one("SELECT * FROM workflows WHERE id=?", (w["id"],))
    assert json.loads(wf["learned"]).get("suggest_auto") is True


def test_preview_edits_are_used_and_reset_trust():
    w = active_workflow()
    learned = {"mode": "preview"}
    db.ex("UPDATE workflows SET learned=? WHERE id=?", (json.dumps(learned), w["id"]))
    rid = start_for(w, 0)
    run(engine.execute(rid))
    run(engine.resolve(rid, edits={"notify": {"text": "Kabir sent the W-9, all good"}}))
    assert any(m["text"] == "Kabir sent the W-9, all good" for m in apps.list_chat("#support"))
    assert json.loads(db.one("SELECT stats FROM workflows WHERE id=?", (w["id"],))["stats"])["clean_streak"] == 0


def test_undo_rolls_back_crm_and_chat():
    w = active_workflow()
    notes_before = len(apps.find_by_email("kabir@finlyte.com")["notes"])
    chat_before = len(apps.list_chat("#support"))
    rid = start_for(w, 0)
    run(engine.execute(rid))
    assert len(apps.list_chat("#support")) == chat_before + 1
    assert run(engine.undo(rid)) is True
    assert engine._load(rid)["status"] == "undone"
    assert len(apps.find_by_email("kabir@finlyte.com")["notes"]) == notes_before
    assert len(apps.list_chat("#support")) == chat_before


def test_self_healing_matches_renamed_ui_by_meaning():
    from app import heal
    save = heal.TARGETS["crm.save"]["words"]
    assert heal.score(save, {"text": "Update record"}) >= 0.5
    assert heal.score(save, {"text": "OrbitMart Meera Pillai"}) < 0.5
    note = heal.TARGETS["crm.note"]["words"]
    assert heal.score(note, {"placeholder": "Describe the customer's request"}) >= 0.5
    assert heal.score(note, {"placeholder": "Search customers"}) < 0.5


def test_change_by_saying_it_offline_parser_and_conditional_step():
    from app import nl_edit
    w = active_workflow()
    spec = json.loads(db.one("SELECT spec FROM workflows WHERE id=?", (w["id"],))["spec"])
    r = nl_edit.propose(spec, "only notify #finance if the attachment is an invoice, and tag Priya")
    assert r["engine"] == "rules" and r["understood"]
    notify = next(s for s in r["spec"]["steps"] if s["action"] == "send_message")
    assert notify["params"]["channel"] == "#finance" and "@Priya" in notify["params"]["text"]
    assert notify["when"]["var"] == "attachment" and "invoice" in notify["when"]["any"]
    db.ex("UPDATE workflows SET spec=? WHERE id=?", (json.dumps(r["spec"]), w["id"]))
    rid = start_for(w, 2)  # purchase order: notification skipped
    run(engine.execute(rid))
    r1 = engine._load(rid)
    assert r1["status"] == "done" and next(s for s in r1["steps"] if s["id"] == "notify")["status"] == "skipped"
    rid = start_for(w, 3)  # invoice: posted in #finance with the tag
    run(engine.execute(rid))
    assert any("@Priya" in m["text"] for m in apps.list_chat("#finance"))


def test_ai_ops_are_validated_before_use():
    from app import nl_edit
    w = active_workflow()
    spec = json.loads(w["spec"])
    bad = [{"op": "delete_everything"}, {"op": "set_channel", "step": "nope-not-a-step", "channel": "#x"},
           {"op": "add_condition", "step": "notify", "var": "salary", "contains": []}, {"op": "remove_step", "step": "read"}]
    ops = [c for c in (nl_edit._clean(o, spec) for o in bad) if c]
    new, changes = nl_edit.apply(spec, ops)
    assert [s["id"] for s in new["steps"]] == [s["id"] for s in spec["steps"]]  # nothing harmful got through


def test_ai_answer_that_adds_a_second_notify_is_merged_correctly(monkeypatch):
    """Regression: the real qwen2.5:3b answered 'add another #finance step' instead of moving the channel."""
    from app import nl_edit
    w = active_workflow()
    spec = json.loads(w["spec"])
    monkeypatch.setattr(llm, "status", lambda: {"engine": "ollama", "model": "qwen2.5:3b", "local": True, "label": ""})
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"ops": [
        {"op": "add_condition", "step": "notify", "var": "attachment", "contains": ["invoice"]},
        {"op": "mention", "step": "notify", "who": "Priya"},
        {"op": "add_notify", "channel": "#finance", "text": "Notify only for invoice attachments and tag Priya"},
        {"op": "mention", "step": "notify", "who": "Anil"}]})
    r = nl_edit.propose(spec, "Only notify #finance if the attachment is an invoice, and tag Priya")
    notifies = [s for s in r["spec"]["steps"] if s["action"] == "send_message"]
    assert len(notifies) == 1
    assert notifies[0]["params"]["channel"] == "#finance" and "@Priya" in notifies[0]["params"]["text"]
    assert "@Anil" not in notifies[0]["params"]["text"] and notifies[0]["when"]["var"] == "attachment"


def test_run_now_never_picks_old_hand_handled_emails():
    from app import main
    w = active_workflow()
    for e in db.q("SELECT id FROM emails WHERE handled_by IS NULL"):
        db.ex("UPDATE emails SET handled_by=999 WHERE id=?", (e["id"],))  # inbox fully processed
    rid = run(main.run_now(w["id"], main.RunIn()))["run_id"]
    r = engine._load(rid)
    assert r["trigger"]["from"] == "Kabir Shah"  # the next test email, not last week's


def _mime(subject="Invoice INV-77", sender="Ravi Kumar <ravi@finlyte.com>", attach=True):
    from email.message import EmailMessage
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, "yash@example.com", subject
    m.set_content("Hi, invoice attached.")
    if attach:
        m.add_attachment(b"%PDF-1.4 real invoice bytes", maintype="application", subtype="pdf", filename="Invoice_INV-77.pdf")
    return m.as_bytes()


class FakeIMAP:
    """Stands in for imap.gmail.com: UIDs 1-3 existed before connecting, 4 (no attachment) and 5 (invoice) are new."""
    MAIL = {1: _mime("old"), 2: _mime("old"), 3: _mime("old"), 4: _mime("Lunch?", attach=False), 5: _mime()}

    def __init__(self, *a, **k): pass
    def login(self, u, p): return "OK", [b""]
    def select(self, *a, **k): return "OK", [b""]
    def logout(self): pass

    def uid(self, cmd, *args):
        if cmd == "search":
            q = args[-1]
            if q == "ALL":
                return "OK", [b"1 2 3"]
            lo = int(q.split()[1].split(":")[0])
            return "OK", [" ".join(str(u) for u in self.MAIL if u >= lo).encode() or b"5"]
        return "OK", [(b"1 (BODY[] {n}", self.MAIL[int(args[0])]), b")"]


def test_gmail_imports_only_new_emails_with_attachments_and_runs_workflow(monkeypatch):
    from app import connectors
    import imaplib
    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeIMAP)
    db.set_setting("gmail_user", "yash@example.com"); db.set_setting("gmail_app_password", "abcd efgh ijkl mnop")
    FakeIMAP.MAIL = {1: _mime("old"), 2: _mime("old"), 3: _mime("old")}
    assert connectors.gmail_connect()["ok"]
    assert db.settings()["gmail_last_uid"] == "3"  # starts from now: old mail is never imported
    FakeIMAP.MAIL.update({4: _mime("Lunch?", attach=False), 5: _mime()})
    new = connectors.gmail_poll()
    assert len(new) == 1
    e = db.one("SELECT * FROM emails WHERE id=?", (new[0],))
    assert e["source"] == "gmail" and e["sender_email"] == "ravi@finlyte.com" and e["attachment"] == "Invoice_INV-77.pdf"
    assert apps.download_attachment(e["id"], actor="automation")[1] == b"%PDF-1.4 real invoice bytes"
    assert connectors.gmail_poll() == []  # nothing imported twice
    w = active_workflow()
    rid = engine.start(w["id"], {"type": "new_email", "email_id": e["id"], "subject": e["subject"], "from": e["sender_name"]})
    run(engine.execute(rid))
    r = engine._load(rid)
    assert r["status"] == "needs_you"  # real sender isn't in the CRM: it stops and asks, suggesting Finlyte by domain
    assert "Kabir" in json.loads(r["note"])["suggested_name"]


def test_slack_gets_the_team_notification_and_undo_posts_a_revert(monkeypatch):
    from app import connectors
    import httpx
    posted = []

    class R:
        status_code, text = 200, "ok"
    monkeypatch.setattr(httpx, "post", lambda url, json=None, timeout=None: posted.append(json["text"]) or R())
    db.set_setting("slack_webhook", "https://hooks.slack.com/services/T0/B0/xyz")
    db.set_setting("api_outage", "0")
    w = active_workflow()

    async def fake_api_chat(action, p, v):  # API tier without a running server: only the Slack branch matters here
        if action == "send_message" and connectors.slack_url():
            connectors.slack_post(f"*{p['channel']}* · {p['text']}")
            apps.post_chat(p["channel"], p["text"], actor="automation")
            return {"slack": True}
        raise engine.StepError("skip")
    monkeypatch.setitem(engine.TIERS, "api", fake_api_chat)
    rid = start_for(w, 0)
    run(engine.execute(rid))
    r = engine._load(rid)
    assert r["status"] == "done" and any("#support" in t and "Kabir" in t for t in posted)
    assert next(s for s in r["steps"] if s["id"] == "notify")["detail"].endswith("on Slack")
    run(engine.undo(rid))
    assert "Undone" in posted[-1]


def test_looking_around_is_never_suggested_as_a_routine():
    """Regression: switching to another app while opening records/channels made 'Update' junk suggestions."""
    base = datetime.now() - timedelta(hours=5)
    for k in range(3):
        t = base + timedelta(minutes=30 * k)
        for dt, (app, action, data) in enumerate([
            ("desktop", "app_focus", {"process": "claude.exe", "title": "Claude"}),
            ("crm", "open_record", {"customer_id": 1}), ("chat", "open_channel", {"channel": "#support"})]):
            db.ex("INSERT INTO events(ts,source,app,action,target,data) VALUES (?,?,?,?,?,?)",
                  ((t + timedelta(seconds=dt * 20)).isoformat(timespec="seconds"), "agent", app, action, "", json.dumps(data)))
    names = [p["steps"] for p in discovery.mine()]
    assert all("chat.post_message" in s or "crm.update_record" in s or "mail.download_attachment" in s for s in names)


# ---------------- noise, duplicates, asking before changing, editing steps ----------------
def _routine_run(t, k, extra=(), notify=True, open_channel=False):
    """One hand-done customer request starting at time t. `extra` = (seconds, app, action, data) events mixed in."""
    c = db.q("SELECT * FROM customers")[k % 6]
    evs = [(0, "mail", "open_email", {"email_id": 1, "from_email": c["email"], "from_name": c["name"], "subject": f"Req {k}", "attachment": f"F{k}.pdf"}),
           (60, "mail", "download_attachment", {"email_id": 1, "filename": f"F{k}.pdf"}),
           (120, "crm", "open_record", {"customer_id": c["id"], "company": c["company"]}),
           (200, "crm", "update_record", {"customer_id": c["id"], "note": f"Customer request: Req {k}", "attachment": f"F{k}.pdf"})]
    if open_channel:
        evs.append((240, "chat", "open_channel", {"channel": "#support"}))
    if notify:
        evs.append((260, "chat", "post_message", {"channel": "#support", "text": f"New request from {c['name']}"}))
    for dt, app, action, data in sorted(evs + list(extra), key=lambda e: e[0]):
        db.ex("INSERT INTO events(ts,source,app,action,target,data) VALUES (?,?,?,?,?,?)",
              ((t + timedelta(seconds=dt)).isoformat(timespec="seconds"), "agent", app, action, "", json.dumps(data)))


def _labels(w):
    return [s["label"] for s in json.loads(w["spec"])["steps"]]


def test_a_quick_glance_at_another_app_or_tab_is_never_a_step():
    """You peek at a chat app and a news tab for a few seconds in the middle of the routine, every time."""
    base = datetime.now() - timedelta(hours=20)
    glance = ((50, "desktop", "app_focus", {"process": "Notepad.exe", "title": "notes"}),   # 3 s
              (53, "web", "navigate", {"domain": "news.example.com", "title": "News"}))       # 7 s, then back to work
    for k in range(4):
        _routine_run(base + timedelta(hours=3 * k), k, extra=glance)
    discovery.refresh()
    ws = db.q("SELECT * FROM workflows")
    assert len(ws) == 1, "the glances must not create a second, noisy suggestion"
    assert not any("Notepad" in l or "news.example.com" in l for l in _labels(ws[0]))
    assert json.loads(ws[0]["pattern"])["support"] == 8  # the 4 demo runs + these 4 are the same routine


def test_staying_in_an_app_or_acting_on_a_page_still_counts_as_work():
    """The filter must not throw away real work: 40 s in Excel is a step, a clicked page is a step."""
    toks, _ = discovery.tokenize([
        {"ts": "2026-01-01T10:00:00", "app": "web", "action": "navigate", "data": json.dumps({"domain": "portal.test"})},
        {"ts": "2026-01-01T10:00:04", "app": "web", "action": "click", "data": json.dumps({"domain": "portal.test", "text": "Export"})},
        {"ts": "2026-01-01T10:00:10", "app": "desktop", "action": "app_focus", "data": json.dumps({"process": "EXCEL.EXE"})},
        {"ts": "2026-01-01T10:00:50", "app": "desktop", "action": "app_focus", "data": json.dumps({"process": "Notepad.exe"})},
        {"ts": "2026-01-01T10:00:53", "app": "mail", "action": "open_email", "data": "{}"}])
    assert toks == ["web.portal.test", "web.portal.test.click:export", "desktop.excel", "mail.open_email"]
    assert db.settings()["min_dwell_sec"] == "10"  # the default: under 10 s with nothing done is a glance
    stay = lambda secs: discovery.tokenize([  # noqa: E731
        {"ts": "2026-01-01T10:00:00", "app": "desktop", "action": "app_focus", "data": json.dumps({"process": "EXCEL.EXE"})},
        {"ts": f"2026-01-01T10:00:{secs:02d}", "app": "mail", "action": "open_email", "data": "{}"}])[0]
    assert stay(9) == ["mail.open_email"] and stay(10) == ["desktop.excel", "mail.open_email"]


def test_never_work_apps_are_ignored_however_long_you_stay():
    base = datetime.now() - timedelta(hours=20)
    video = ((1, "web", "navigate", {"domain": "www.youtube.com", "title": "YouTube"}),
             (5, "web", "click", {"domain": "www.youtube.com", "text": "Play"}),
             (25, "desktop", "app_focus", {"process": "WhatsApp.exe", "title": "WhatsApp"}))
    for k in range(4):
        _routine_run(base + timedelta(hours=3 * k), k, extra=video)  # 40 s of video + chat before carrying on
    discovery.refresh()
    ws = db.q("SELECT * FROM workflows")
    assert len(ws) == 1 and not any("youtube" in l.lower() or "whatsapp" in l.lower() for l in _labels(ws[0]))
    # the list is yours to edit: take an app off it and it counts again
    db.set_setting("ignore_apps", "youtube")
    assert "whatsapp" not in discovery.ignore_list() and "youtube" in discovery.ignore_list()
    assert not discovery._ignored({"app": "web", "data": json.dumps({"domain": "dropbox.com"})}, ["x.com"])


def test_the_same_routine_is_never_suggested_twice():
    """Even with the noise filter off, variations and pieces of one routine are one suggestion."""
    db.set_setting("min_dwell_sec", "0"); db.set_setting("ignore_apps", "")
    base = datetime.now() - timedelta(hours=20)
    noise = ((30, "desktop", "app_focus", {"process": "Notepad.exe", "title": "notes"}),)
    for k in range(4):
        _routine_run(base + timedelta(hours=3 * k), k, extra=noise)
    discovery.refresh()
    assert [w["name"] for w in db.q("SELECT * FROM workflows")] == ["Process customer request"]
    discovery.refresh()  # and looking again doesn't add anything
    assert db.one("SELECT COUNT(*) n FROM workflows")["n"] == 1


def test_a_dismissed_routine_does_not_come_back_as_a_variation():
    discovery.refresh()
    w = db.one("SELECT * FROM workflows")
    db.ex("UPDATE workflows SET status='dismissed' WHERE id=?", (w["id"],))
    base = datetime.now() - timedelta(hours=10)
    for k in range(3):
        _routine_run(base + timedelta(hours=2 * k), k, notify=False)  # now without telling the team
    discovery.refresh()
    ws = db.q("SELECT * FROM workflows")
    assert len(ws) == 1 and ws[0]["status"] == "dismissed" and "proposal" not in json.loads(ws[0]["learned"])


def test_a_new_way_of_working_is_proposed_not_applied_and_asks_only_once():
    w = active_workflow()
    before = db.one("SELECT spec FROM workflows WHERE id=?", (w["id"],))["spec"]
    base = datetime.now() - timedelta(hours=10)
    for k in range(3):
        _routine_run(base + timedelta(hours=2 * k), k, notify=False)
    discovery.refresh()
    ws = db.q("SELECT * FROM workflows")
    assert len(ws) == 1, "a variation of an approved workflow is not a new suggestion"
    assert [s["id"] for s in json.loads(ws[0]["spec"])["steps"]] == [s["id"] for s in json.loads(before)["steps"]]  # untouched
    prop = json.loads(ws[0]["learned"])["proposal"]
    assert prop["removed"] == ["Notify the team in #support"] and prop["added"] == []
    # "Keep mine": the workflow stays as it is and the same variation is never proposed again
    discovery.answer_proposal(w["id"], accept=False)
    discovery.refresh()
    kept = db.one("SELECT * FROM workflows WHERE id=?", (w["id"],))
    assert "proposal" not in json.loads(kept["learned"]) and len(json.loads(kept["spec"])["steps"]) == 5
    assert db.one("SELECT COUNT(*) n FROM workflows")["n"] == 1


def test_accepting_a_proposal_keeps_your_own_edits_and_added_steps():
    from app import steps
    w = active_workflow()
    spec = json.loads(db.one("SELECT spec FROM workflows WHERE id=?", (w["id"],))["spec"])
    next(s for s in spec["steps"] if s["id"] == "update")["params"]["note"] = "MY WORDING {{subject}}"
    spec, _ = steps.add_step(spec, "find", "manual", {"label": "Check the contract in the shared drive"})
    db.ex("UPDATE workflows SET spec=? WHERE id=?", (json.dumps({**spec, "edited": True}), w["id"]))
    base = datetime.now() - timedelta(hours=10)
    for k in range(3):
        _routine_run(base + timedelta(hours=2 * k), k, notify=False)
    discovery.refresh()
    assert json.loads(db.one("SELECT learned FROM workflows WHERE id=?", (w["id"],))["learned"])["proposal"]["removed"] == ["Notify the team in #support"]
    discovery.answer_proposal(w["id"], accept=True)
    new = json.loads(db.one("SELECT spec FROM workflows WHERE id=?", (w["id"],))["spec"])
    assert [s["action"] for s in new["steps"]] == ["read_email", "download_attachment", "find_customer", "manual", "update_customer"]
    assert next(s for s in new["steps"] if s["id"] == "update")["params"]["note"] == "MY WORDING {{subject}}"
    discovery.refresh()  # the old way (with the team message) is history: it isn't proposed back
    assert "proposal" not in json.loads(db.one("SELECT learned FROM workflows WHERE id=?", (w["id"],))["learned"])
    assert db.one("SELECT COUNT(*) n FROM workflows")["n"] == 1


def test_steps_can_be_removed_and_added_in_between_but_never_into_a_broken_workflow():
    from app import steps
    w = active_workflow()
    spec = json.loads(w["spec"])
    with pytest.raises(steps.EditError, match="needs the customer id"):
        steps.delete_step(spec, "find")          # "Update the customer record" still needs the customer
    with pytest.raises(steps.EditError, match="after"):
        steps.add_step(spec, "read", "crm_note", {"note": "too early"})  # no customer found yet at that point
    with pytest.raises(steps.EditError, match="isn't known yet"):
        steps.add_step(spec, None, "notify", {"channel": "#ops", "text": "{{customer_name}} wrote"})
    with pytest.raises(steps.EditError):
        steps.add_step(spec, "find", "open_page", {"url": "javascript:alert(1)"})
    spec, _ = steps.delete_step(spec, "notify")
    spec, _ = steps.add_step(spec, "find", "notify", {"channel": "finance", "text": "Heads up: {{customer_name}} ({{company}}) sent {{attachment}}"})
    assert [s["action"] for s in spec["steps"]] == ["read_email", "download_attachment", "find_customer", "send_message", "update_customer"]
    db.ex("UPDATE workflows SET spec=? WHERE id=?", (json.dumps(spec), w["id"]))
    rid = start_for(w, 0)
    run(engine.execute(rid))
    assert engine._load(rid)["status"] == "done"
    assert any(m["text"] == "Heads up: Kabir Shah (Finlyte) sent W9_Finlyte_2026.pdf" for m in apps.list_chat("#finance"))
    assert not any("Kabir" in m["text"] and m["bot"] for m in apps.list_chat("#support"))  # the removed step didn't run


def test_only_this_computer_and_the_extension_may_call_the_server():
    from app import main
    ok = main.origin_allowed
    assert ok(None)                                            # desktop agent: not a browser, no Origin header
    assert ok("http://localhost:8765") and ok("http://127.0.0.1:5173")
    assert ok("chrome-extension://abcdefghijklmnop")
    assert ok("http://192.168.1.7:5173", host="192.168.1.7:5173")   # the page that served the app
    assert not ok("https://evil.example") and not ok("https://evil.example", host="localhost:8765")
    assert not ok("http://localhost.evil.example")
