"""WorkFlowOS API: observe -> discover -> approve -> automate -> learn."""
import asyncio
import json
import os
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import apps, connectors, db, discovery, engine, llm, nl_edit, sim

app = FastAPI(title="WorkFlowOS")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
AGENTS: dict[str, dict] = {}  # name -> {source, last_seen, info}


class Hub:
    def __init__(self):
        self.conns: list[WebSocket] = []

    async def send(self, ev: dict):
        for ws in list(self.conns):
            try:
                await ws.send_json(ev)
            except Exception:
                if ws in self.conns:
                    self.conns.remove(ws)


hub = Hub()


async def _notify_run(run_id: int):
    await hub.send({"type": "run", "run_id": run_id})


engine._notify = _notify_run


def actor(req: Request) -> str:
    auto = req.headers.get("x-actor") == "automation" or req.query_params.get("actor") == "automation"
    return "automation" if auto else "user"


def wf_out(w):
    w = dict(w)
    for k in ("spec", "pattern", "learned", "stats"):
        w[k] = db.js(w[k], {})
    return w


def run_out(r):
    r = dict(r)
    for k in ("trigger", "vars", "steps"):
        r[k] = db.js(r[k], {} if k != "steps" else [])
    r["note"] = db.js(r["note"], {}) if r["note"] else {}
    return r


async def on_activity():
    await hub.send({"type": "activity"})


async def auto_discover():
    """Re-mine patterns after new activity (cheap on this data size)."""
    before = {w["id"]: db.js(w["pattern"], {}).get("support") for w in db.q("SELECT * FROM workflows")}
    ids = await asyncio.to_thread(discovery.refresh)
    after = {w["id"]: db.js(w["pattern"], {}).get("support") for w in db.q("SELECT * FROM workflows")}
    changed = [i for i in ids if before.get(i) != after.get(i)]
    await hub.send({"type": "workflows", "changed": changed})


# ---------------- state / settings ----------------
@app.get("/api/state")
def state():
    s = db.settings()
    safe = {k: v for k, v in s.items() if k not in ("groq_key", "jev_key", "gmail_app_password", "slack_webhook")}
    now = datetime.now()
    agents = [{"name": n, **a, "online": (now - datetime.fromisoformat(a["last_seen"])).total_seconds() < 30}
              for n, a in AGENTS.items()]
    wfs = [wf_out(w) for w in db.q("SELECT * FROM workflows")]
    saved = sum(w["stats"].get("time_saved_sec", 0) for w in wfs)
    runs = db.one("SELECT COUNT(*) n FROM runs")["n"]
    ai = llm.status()
    return {"settings": safe, "llm": ai["engine"] != "rules", "ai": ai, "agents": agents, "connectors": connectors.status(),
            "groq_key_set": bool(s.get("groq_key", "").strip()),
            "counts": {"events": db.one("SELECT COUNT(*) n FROM events")["n"], "runs": runs,
                       "active": sum(1 for w in wfs if w["status"] == "active"),
                       "suggested": sum(1 for w in wfs if w["status"] == "suggested"), "time_saved_sec": saved}}


class SettingsIn(BaseModel):
    observing: bool | None = None
    api_outage: bool | None = None
    app_outage: bool | None = None
    show_browser: bool | None = None
    ui_v2: bool | None = None
    ai_local_only: bool | None = None
    ollama_model: str | None = None
    user_name: str | None = None
    groq_key: str | None = None


@app.put("/api/settings")
async def put_settings(s: SettingsIn):
    for k, v in s.model_dump(exclude_none=True).items():
        db.set_setting(k, ("1" if v else "0") if isinstance(v, bool) else v)
    llm._ollama["checked"] = 0  # re-detect the local model after any settings change
    await hub.send({"type": "state"})
    return state()


# ---------------- observation ----------------
class EventIn(BaseModel):
    app: str
    action: str
    target: str = ""
    data: dict = {}
    source: str = "agent"
    ts: str | None = None


@app.post("/api/events")
async def post_events(body: EventIn | list[EventIn]):
    evs = body if isinstance(body, list) else [body]
    if db.settings().get("observing") != "1":
        return {"stored": 0, "observing": False}
    n = 0
    for e in evs:
        db.ex("INSERT INTO events(ts, source, app, action, target, data) VALUES (?,?,?,?,?,?)",
              (e.ts or db.now(), e.source, e.app, e.action, e.target[:200], json.dumps(e.data)[:4000]))
        n += 1
    await _after_user_action()  # stream it and re-run discovery once activity settles
    return {"stored": n, "observing": True}


class Heartbeat(BaseModel):
    name: str
    source: str
    info: dict = {}


@app.post("/api/agents/heartbeat")
async def heartbeat(h: Heartbeat):
    new = h.name not in AGENTS
    AGENTS[h.name] = {"source": h.source, "last_seen": db.now(), "info": h.info}
    if new:
        await hub.send({"type": "state"})
    return {"observing": db.settings().get("observing") == "1"}


@app.get("/api/events")
def get_events(limit: int = 60):
    rows = db.q("SELECT * FROM events ORDER BY ts DESC, id DESC LIMIT ?", (limit,))
    for r in rows:
        r["data"] = db.js(r["data"], {})
    return rows


# ---------------- discovery / workflows ----------------
@app.post("/api/discover")
async def discover():
    await auto_discover()
    return [wf_out(w) for w in db.q("SELECT * FROM workflows ORDER BY id")]


@app.get("/api/workflows")
def list_workflows():
    order = {"active": 0, "suggested": 1, "paused": 2, "dismissed": 3}
    rows = [wf_out(w) for w in db.q("SELECT * FROM workflows")]
    return sorted(rows, key=lambda w: (order.get(w["status"], 9), -w["pattern"].get("score", 0)))


@app.get("/api/workflows/{wid}")
def get_workflow(wid: int):
    w = db.one("SELECT * FROM workflows WHERE id=?", (wid,))
    if not w:
        raise HTTPException(404)
    runs = [run_out(r) for r in db.q("SELECT * FROM runs WHERE workflow_id=? ORDER BY id DESC LIMIT 20", (wid,))]
    pat = db.js(w["pattern"], {})
    return {"workflow": wf_out(w), "runs": runs}


class WorkflowPatch(BaseModel):
    status: str | None = None
    spec: dict | None = None
    name: str | None = None
    mode: str | None = None  # preview | auto
    said: str | None = None  # the sentence that produced this spec change


@app.patch("/api/workflows/{wid}")
async def patch_workflow(wid: int, body: WorkflowPatch):
    w = db.one("SELECT * FROM workflows WHERE id=?", (wid,))
    if not w:
        raise HTTPException(404)
    if body.status in ("active", "paused", "dismissed", "suggested"):
        db.ex("UPDATE workflows SET status=?, updated_at=? WHERE id=?", (body.status, db.now(), wid))
        learned = db.js(w["learned"], {}) or {}
        if body.status == "active" and "mode" not in learned:
            learned["mode"] = "preview"  # new automations earn their autonomy
            db.ex("UPDATE workflows SET learned=? WHERE id=?", (json.dumps(learned), wid))
    if body.mode in ("preview", "auto"):
        learned = db.js(db.one("SELECT learned FROM workflows WHERE id=?", (wid,))["learned"], {}) or {}
        learned["mode"] = body.mode
        learned.pop("suggest_auto", None)
        learned.setdefault("log", []).append("You put it on autopilot" if body.mode == "auto" else "You asked to preview changes first")
        db.ex("UPDATE workflows SET learned=? WHERE id=?", (json.dumps(learned), wid))
    if body.spec:
        learned = db.js(w["learned"], {}) or {}
        learned.setdefault("log", []).append(f'You said: "{body.said[:120]}"' if body.said else "You edited the workflow")
        db.ex("UPDATE workflows SET spec=?, learned=?, updated_at=? WHERE id=?",
              (json.dumps({**body.spec, "edited": True}), json.dumps(learned), db.now(), wid))
    if body.name:
        db.ex("UPDATE workflows SET name=? WHERE id=?", (body.name, wid))
    await hub.send({"type": "workflows"})
    return wf_out(db.one("SELECT * FROM workflows WHERE id=?", (wid,)))


def _trigger_matches(spec, email):
    t = spec.get("trigger", {})
    return t.get("type") == "new_email" and (not t.get("has_attachment") or email["attachment"])


async def _start_run(wid, email):
    rid = engine.start(wid, {"type": "new_email", "email_id": email["id"], "subject": email["subject"],
                             "from": email["sender_name"]})
    await hub.send({"type": "run", "run_id": rid, "started": True})
    asyncio.create_task(engine.execute(rid))
    return rid


class RunIn(BaseModel):
    email_id: int | None = None


@app.post("/api/workflows/{wid}/run")
async def run_now(wid: int, body: RunIn):
    w = db.one("SELECT * FROM workflows WHERE id=?", (wid,))
    if not w:
        raise HTTPException(404)
    if (db.js(w["spec"], {}).get("trigger") or {}).get("type") != "new_email":
        rid = engine.start(wid, {"type": "manual", "subject": w["name"], "from": "you (Run now)"})
        await hub.send({"type": "run", "run_id": rid, "started": True})
        asyncio.create_task(engine.execute(rid))
        return {"run_id": rid}
    email = db.one("SELECT * FROM emails WHERE id=?", (body.email_id,)) if body.email_id else \
        db.one("SELECT * FROM emails WHERE handled_by IS NULL AND attachment!='' ORDER BY received_at DESC LIMIT 1")
    if not email:  # nothing new in the inbox: bring in the next test email (it starts the run itself)
        runs = await _new_email(sim.test_email(_next_test_email()))
        if runs:
            return {"run_id": runs[0]}
        raise HTTPException(400, "No new email to run on")
    return {"run_id": await _start_run(wid, email)}


def _next_test_email() -> int:
    i = int(db.settings().get("test_email_n") or 0)
    db.set_setting("test_email_n", str(i + 1))
    return i


@app.get("/api/runs")
def list_runs(limit: int = 30):
    rows = [run_out(r) for r in db.q("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))]
    names = {w["id"]: w["name"] for w in db.q("SELECT id, name FROM workflows")}
    for r in rows:
        r["workflow_name"] = names.get(r["workflow_id"], "Workflow")
    return rows


@app.get("/api/runs/{rid}")
def get_run(rid: int):
    r = db.one("SELECT * FROM runs WHERE id=?", (rid,))
    if not r:
        raise HTTPException(404)
    out = run_out(r)
    out["workflow_name"] = (db.one("SELECT name FROM workflows WHERE id=?", (r["workflow_id"],)) or {}).get("name")
    return out


class ResolveIn(BaseModel):
    customer_id: int | None = None
    create: dict | None = None
    remember: bool = True
    edits: dict | None = None
    cancel: bool = False


@app.post("/api/runs/{rid}/resolve")
async def resolve(rid: int, body: ResolveIn):
    asyncio.create_task(engine.resolve(rid, body.customer_id, body.create, body.remember, body.edits, body.cancel))
    return {"ok": True}


class AskIn(BaseModel):
    text: str


@app.post("/api/workflows/{wid}/ask")
async def ask_workflow(wid: int, body: AskIn):
    """Change a workflow by saying it: returns a proposal + diff. Nothing is saved until you approve."""
    w = db.one("SELECT * FROM workflows WHERE id=?", (wid,))
    if not w:
        raise HTTPException(404)
    if not body.text.strip():
        raise HTTPException(400, "Say what to change")
    return await asyncio.to_thread(nl_edit.propose, db.js(w["spec"], {}), body.text.strip()[:400])


@app.get("/api/ai")
async def ai_status():
    return await asyncio.to_thread(llm.status)


@app.post("/api/runs/{rid}/undo")
async def undo_run(rid: int):
    if not await engine.undo(rid):
        raise HTTPException(400, "Only a finished run can be undone")
    await hub.send({"type": "apps", "app": "all"})
    await hub.send({"type": "workflows"})
    return {"ok": True}


# ---------------- demo apps ----------------
@app.get("/api/apps/mail")
def mail_list():
    return apps.list_emails()


@app.get("/api/apps/mail/{eid}")
async def mail_get(eid: int, request: Request):
    e = apps.get_email(eid, actor(request))
    if not e:
        raise HTTPException(404)
    if actor(request) == "user":
        asyncio.create_task(_after_user_action())
    return e


@app.get("/api/apps/mail/{eid}/attachment")
async def mail_attachment(eid: int, request: Request):
    res = apps.download_attachment(eid, actor(request))
    if not res:
        raise HTTPException(404)
    if actor(request) == "user":
        asyncio.create_task(_after_user_action())
    return Response(res[1], media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{res[0]}"'})


class MailIn(BaseModel):
    sender_name: str
    sender_email: str
    subject: str
    body: str = ""
    attachment: str = ""


async def _new_email(eid):
    email = db.one("SELECT * FROM emails WHERE id=?", (eid,))
    await hub.send({"type": "apps", "app": "mail"})
    started = []
    for w in db.q("SELECT * FROM workflows WHERE status='active'"):
        if _trigger_matches(db.js(w["spec"], {}), email):
            started.append(await _start_run(w["id"], email))
    return started


@app.post("/api/apps/mail/receive")
async def mail_receive(m: MailIn):
    eid = apps.receive_email(m.sender_name, m.sender_email, m.subject, m.body, m.attachment)
    return {"email_id": eid, "runs": await _new_email(eid)}


@app.post("/api/demo/test-email")
async def test_email(i: int = -1):
    if i < 0:
        i = _next_test_email()
    eid = sim.test_email(i)
    return {"email_id": eid, "runs": await _new_email(eid)}


@app.get("/api/apps/crm")
async def crm_list(request: Request, q: str = ""):
    res = apps.search_customers(q, actor(request))
    if q and actor(request) == "user":
        asyncio.create_task(_after_user_action())
    return res


@app.get("/api/apps/crm/find")
def crm_find(email: str):
    c = apps.find_by_email(email)
    if not c:
        raise HTTPException(404, "not found")
    return c


@app.get("/api/apps/crm/{cid}")
async def crm_get(cid: int, request: Request, quiet: int = 0):
    who = "automation" if quiet else actor(request)  # quiet = a UI refresh, not a user action
    c = apps.get_customer(cid, who)
    if not c:
        raise HTTPException(404)
    if who == "user":
        asyncio.create_task(_after_user_action())
    return c


class CrmUpdate(BaseModel):
    note: str
    attachment: str = ""


@app.put("/api/apps/crm/{cid}")
async def crm_update(cid: int, body: CrmUpdate, request: Request):
    c = apps.update_customer(cid, body.note, body.attachment, actor(request))
    if not c:
        raise HTTPException(404)
    await hub.send({"type": "apps", "app": "crm"})
    if actor(request) == "user":
        asyncio.create_task(_after_user_action())
    return c


class ChatIn(BaseModel):
    channel: str
    text: str


@app.get("/api/apps/chat")
async def chat_list(request: Request, channel: str = "#support", open: int = 0):
    ch = channel if channel.startswith("#") else "#" + channel
    if open and actor(request) == "user":  # the person switched to this channel
        apps.emit("chat", "open_channel", {"channel": ch}, target=ch)
        asyncio.create_task(_after_user_action())
    return {"channels": apps.channels(), "messages": apps.list_chat(ch)}


@app.post("/api/apps/chat")
async def chat_post(body: ChatIn, request: Request):
    ch = body.channel if body.channel.startswith("#") else "#" + body.channel
    mid = apps.post_chat(ch, body.text, actor(request))
    await hub.send({"type": "apps", "app": "chat"})
    if actor(request) == "user":
        asyncio.create_task(_after_user_action())
    return {"id": mid}


_pending_discover = {"task": None}


async def _after_user_action():
    """Live observation: stream the activity and re-run discovery shortly after the user stops."""
    await on_activity()
    t = _pending_discover.get("task")
    if t and not t.done():
        t.cancel()

    async def later():
        await asyncio.sleep(2.0)
        await auto_discover()
    _pending_discover["task"] = asyncio.create_task(later())


# ---------------- observed sessions (for the timeline) ----------------
@app.get("/api/sessions")
def get_sessions(days: int = 7):
    st = db.settings()
    events = db.q("SELECT * FROM events ORDER BY ts, id")
    wfs = [wf_out(w) for w in db.q("SELECT * FROM workflows WHERE status!='dismissed'")]
    out = []
    for sess in discovery.sessions(events, float(st.get("session_gap_min", 4))):
        toks, groups = discovery.tokenize(sess)
        matched = []
        for w in wfs:
            m = discovery.match(w["pattern"].get("steps", []), toks) if w["pattern"].get("steps") else None
            if m:
                matched.append({"id": w["id"], "name": w["name"], "idx": m})
        evs = []
        for e in sess:
            e = dict(e)
            e["data"] = db.js(e["data"], {})
            evs.append(e)
        out.append({"start": sess[0]["ts"], "end": sess[-1]["ts"], "events": evs, "tokens": toks,
                    "apps": list(dict.fromkeys(e["app"] for e in sess)), "matched": matched})
    return list(reversed(out))[:60]


# ---------------- downloads: desktop agent + browser extension ----------------
ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


@app.get("/downloads/wfos_agent.py")
def dl_agent():
    return FileResponse(os.path.join(ROOT, "agent", "wfos_agent.py"), filename="wfos_agent.py")


@app.get("/downloads/wfos_extension.zip")
def dl_extension():
    import io
    import zipfile
    buf = io.BytesIO()
    ext = os.path.join(ROOT, "extension")
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for dp, _, fn in os.walk(ext):
            for f in fn:
                full = os.path.join(dp, f)
                z.write(full, os.path.join("wfos_extension", os.path.relpath(full, ext)))
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="wfos_extension.zip"'})


# ---------------- demo controls ----------------
@app.post("/api/demo/reset")
async def reset_demo():
    keep = {k: db.settings().get(k) for k in ("user_name", "groq_key", "gmail_user", "gmail_app_password", "gmail_last_uid",
                                              "slack_webhook", "ai_local_only", "ollama_model")}
    await asyncio.to_thread(sim.seed)
    for k, v in keep.items():
        if v is not None:
            db.set_setting(k, v)
    for k in ("api_outage", "app_outage", "ui_v2"):
        db.set_setting(k, "0")
    db.set_setting("test_email_n", "0")
    db.set_setting("observing", "1")
    await auto_discover()
    await hub.send({"type": "state"})
    await hub.send({"type": "apps", "app": "all"})
    return {"ok": True}


# ---------------- websocket + static ----------------
@app.websocket("/ws")
async def ws(ws: WebSocket):
    await ws.accept()
    hub.conns.append(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if ws in hub.conns:
            hub.conns.remove(ws)


@app.on_event("startup")
async def startup():
    if not db.one("SELECT id FROM customers LIMIT 1"):
        await asyncio.to_thread(sim.seed)
        await asyncio.to_thread(discovery.refresh)
    asyncio.create_task(_gmail_loop())


async def _gmail_loop():
    """Every 15 s: bring new Gmail emails with attachments into Mailbox; active workflows start on them."""
    while True:
        await asyncio.sleep(15)
        if not connectors.gmail_enabled():
            continue
        try:
            new = await asyncio.to_thread(connectors.gmail_poll)
        except Exception as e:  # noqa: BLE001
            connectors.STATUS["gmail"]["error"] = f"Gmail check failed: {str(e)[:120]}"
            continue
        for eid in new:
            await _new_email(eid)
        if new:
            await hub.send({"type": "state"})


class GmailIn(BaseModel):
    user: str = ""
    app_password: str = ""


@app.post("/api/connectors/gmail")
async def connect_gmail(body: GmailIn):
    if not body.user.strip():  # disconnect
        db.set_setting("gmail_app_password", "")
        await hub.send({"type": "state"})
        return {"ok": True, "message": "Gmail disconnected."}
    db.set_setting("gmail_user", body.user.strip())
    if body.app_password.strip():
        db.set_setting("gmail_app_password", body.app_password.replace(" ", "").strip())
    res = await asyncio.to_thread(connectors.gmail_connect)
    if not res["ok"]:
        db.set_setting("gmail_app_password", "")
    await hub.send({"type": "state"})
    return res


@app.post("/api/connectors/gmail/check")
async def check_gmail():
    """Check the inbox right now (used by the 'Check now' button)."""
    if not connectors.gmail_enabled():
        raise HTTPException(400, "Gmail isn't connected")
    try:
        new = await asyncio.to_thread(connectors.gmail_poll)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Gmail check failed: {str(e)[:120]}")
    runs = []
    for eid in new:
        runs += await _new_email(eid)
    await hub.send({"type": "state"})
    return {"imported": len(new), "runs": runs}


class SlackIn(BaseModel):
    webhook: str = ""


@app.post("/api/connectors/slack")
async def connect_slack(body: SlackIn):
    db.set_setting("slack_webhook", body.webhook.strip())
    if not body.webhook.strip():
        await hub.send({"type": "state"})
        return {"ok": True, "message": "Slack disconnected."}
    res = await asyncio.to_thread(connectors.slack_connect)
    if not res["ok"]:
        db.set_setting("slack_webhook", "")
    await hub.send({"type": "state"})
    return res


import mimetypes  # noqa: E402

# some Windows machines map .js to text/plain in the registry, which makes browsers refuse the app
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")
DIST = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
if os.path.isdir(DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST, "assets")), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = os.path.join(DIST, path)
        if path and os.path.isfile(f):
            return FileResponse(f)
        # never cache the page itself, so an updated app is picked up on the next refresh
        return FileResponse(os.path.join(DIST, "index.html"), headers={"Cache-Control": "no-cache"})
