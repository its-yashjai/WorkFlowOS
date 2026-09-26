"""Automation Engine: runs approved workflows step by step.

Every step tries the most reliable mechanism first and falls back:
  1. API integration        (HTTP API of the app)
  2. Application integration (the app's SDK / in-process service)
  3. Browser automation     (Playwright drives the web UI)
  4. Vision / UI fallback   (not needed for these apps)
Conditions (e.g. customer not found) stop the run and ask the user. The answer is
learned so the same situation is handled automatically next time.
"""
import asyncio
import json
import os
import re
import time

import httpx

from . import apps, connectors, db, heal, nl_edit

PORT = int(os.environ.get("WFOS_PORT", "8765"))
BASE = f"http://127.0.0.1:{PORT}"
TIER_LABEL = {"api": "API integration", "app": "Application integration", "browser": "Browser automation",
              "vision": "Vision / UI fallback", "you": "You"}
FILES_DIR = os.path.join(os.path.dirname(__file__), "..", "files")
PROFILE_DIR = os.environ.get("WFOS_BROWSER_PROFILE", os.path.join(os.path.dirname(__file__), "..", ".browser-profile"))
_notify = None  # async callback set by main: notify(run_id)


_BROWSER_LOCK = asyncio.Lock()  # one persistent browser profile can only be open once


class StepError(Exception):
    pass


class NeedsUser(Exception):
    def __init__(self, reason, options=None):
        super().__init__(reason)
        self.reason, self.options = reason, options or {}


def render(tpl, vars_):
    if not isinstance(tpl, str):
        return tpl
    return re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: str(vars_.get(m.group(1), "") or ""), tpl).strip()


def _save_run(run):
    db.ex("UPDATE runs SET status=?, vars=?, steps=?, note=?, finished_at=? WHERE id=?",
          (run["status"], json.dumps(run["vars"]), json.dumps(run["steps"]), run.get("note", ""),
           run.get("finished_at"), run["id"]))


async def _ping(run):
    _save_run(run)
    if _notify:
        try:
            await _notify(run["id"])
        except Exception:  # noqa: BLE001 - a UI notification must never break a run
            pass


# ---------------- tier implementations per action ----------------
async def _api(action, p, v):
    if db.settings().get("api_outage") == "1":
        raise StepError("API unreachable (503, simulated outage)")
    h = {"X-Actor": "automation"}
    async with httpx.AsyncClient(base_url=BASE, timeout=8, headers=h) as c:
        if action == "read_email":
            r = await c.get(f"/api/apps/mail/{p['email_id']}")
        elif action == "download_attachment":
            r = await c.get(f"/api/apps/mail/{p['email_id']}/attachment")
            if r.status_code == 200:
                os.makedirs(FILES_DIR, exist_ok=True)
                with open(os.path.join(FILES_DIR, v.get("attachment") or "attachment.pdf"), "wb") as f:
                    f.write(r.content)
                return {"attachment": v.get("attachment"), "saved_to": "files/" + (v.get("attachment") or "")}
        elif action == "find_customer":
            r = await c.get("/api/apps/crm/find", params={"email": p["email"]})
        elif action == "update_customer":
            r = await c.put(f"/api/apps/crm/{p['customer_id']}", json={"note": p["note"], "attachment": p.get("attachment", "")})
        elif action == "send_message":
            if connectors.slack_url():  # the real Slack workspace
                try:
                    await asyncio.to_thread(connectors.slack_post, f"*{p['channel']}* · {p['text']}")
                except Exception as e:  # noqa: BLE001
                    raise StepError(f"Slack: {str(e)[:100]}")
                apps.post_chat(p["channel"], p["text"], actor="automation")  # mirror, so it shows in the app too
                return {"slack": True}
            r = await c.post("/api/apps/chat", json={"channel": p["channel"], "text": p["text"]})
        else:
            raise StepError("No API for this action")
    if r.status_code == 404 and action == "find_customer":
        return {"customer_id": None}
    if r.status_code >= 400:
        raise StepError(f"API error {r.status_code}")
    return r.json()


async def _app(action, p, v):
    if db.settings().get("app_outage") == "1":
        raise StepError("Application integration disabled (simulated)")
    if action == "read_email":
        return apps.get_email(p["email_id"], actor="automation")
    if action == "download_attachment":
        res = apps.download_attachment(p["email_id"], actor="automation")
        if not res:
            raise StepError("No attachment on this email")
        os.makedirs(FILES_DIR, exist_ok=True)
        with open(os.path.join(FILES_DIR, res[0]), "wb") as f:
            f.write(res[1])
        return {"attachment": res[0], "saved_to": "files/" + res[0]}
    if action == "find_customer":
        c = apps.find_by_email(p["email"])
        return c or {"customer_id": None}
    if action == "update_customer":
        return apps.update_customer(int(p["customer_id"]), p["note"], p.get("attachment", ""), actor="automation")
    if action == "send_message":
        return {"id": apps.post_chat(p["channel"], p["text"], actor="automation")}
    raise StepError("No integration for this action")


async def _browser(action, p, v):
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise StepError("Playwright not installed on this machine")
    show = db.settings().get("show_browser") == "1"
    async with _BROWSER_LOCK, async_playwright() as pw:
        # one persistent profile, so sites you log into once stay logged in for automation
        b = await pw.chromium.launch_persistent_context(PROFILE_DIR, headless=not show, slow_mo=250 if show else 0,
                                                        accept_downloads=True)
        pg = b.pages[0] if b.pages else await b.new_page()
        try:
            if action == "open_page":
                r = await pg.goto(p["url"], wait_until="domcontentloaded", timeout=15000)
                if r and r.status >= 400:
                    raise StepError(f"Page returned {r.status}")
                if show:
                    await pg.wait_for_timeout(800)
                return {"via": "browser", "title": await pg.title()}
            if action == "click":
                await pg.goto(p["url"], wait_until="domcontentloaded", timeout=15000)
                txt = p["text"]
                loc = pg.get_by_role("button", name=txt).or_(pg.get_by_role("link", name=txt)).or_(pg.get_by_text(txt, exact=False))
                if not await loc.count():
                    raise StepError(f"Couldn't find \"{txt}\" on the page")
                try:
                    async with pg.expect_download(timeout=4000) as dl:
                        await loc.first.click()
                    d = await dl.value
                    os.makedirs(FILES_DIR, exist_ok=True)
                    await d.save_as(os.path.join(FILES_DIR, d.suggested_filename))
                    return {"via": "browser", "downloaded": d.suggested_filename}
                except Exception as e:
                    if isinstance(e, StepError):
                        raise
                    await pg.wait_for_timeout(600)
                    return {"via": "browser", "clicked": txt}
            if action == "read_email":
                await pg.goto(f"{BASE}/apps/mail?email={p['email_id']}&actor=automation")
                frm = pg.locator("[data-testid=mail-from]")
                await frm.wait_for(timeout=6000)
                att = pg.locator("[data-testid=mail-attachment]")
                return {"sender_name": await frm.get_attribute("data-name"), "sender_email": await frm.get_attribute("data-email"),
                        "subject": await pg.inner_text("[data-testid=mail-subject]"),
                        "attachment": await att.get_attribute("data-name") if await att.count() else None, "via": "web UI"}
            if action == "download_attachment":
                await pg.goto(f"{BASE}/apps/mail?email={p['email_id']}&actor=automation")
                await pg.wait_for_selector("[data-testid=mail-attachment]", timeout=6000)
                async with pg.expect_download() as dl:
                    await pg.click("[data-testid=mail-attachment]")
                d = await dl.value
                os.makedirs(FILES_DIR, exist_ok=True)
                await d.save_as(os.path.join(FILES_DIR, d.suggested_filename))
                return {"attachment": d.suggested_filename, "saved_to": "files/" + d.suggested_filename, "via": "web UI"}
            if action == "find_customer":
                await pg.goto(f"{BASE}/apps/crm?actor=automation")
                await pg.fill("[data-testid=crm-search]", p["email"])
                await pg.wait_for_timeout(900)
                for row in await pg.locator("[data-testid=crm-row]").all():
                    if (await row.get_attribute("data-email") or "").lower() == (p["email"] or "").lower():
                        return {"id": int(await row.get_attribute("data-id")), "name": await row.get_attribute("data-name"),
                                "company": await row.get_attribute("data-company"), "via": "web UI"}
                return {"customer_id": None}
            if action == "update_customer":
                await pg.goto(f"{BASE}/apps/crm?customer={p['customer_id']}&actor=automation", wait_until="networkidle")
                await (await heal.locate(pg, "crm.note")).fill(p["note"])
                if p.get("attachment"):
                    await (await heal.locate(pg, "crm.attachment")).fill(p["attachment"])
                await (await heal.locate(pg, "crm.save")).click()
                await pg.wait_for_timeout(700)
                c = apps.get_customer(int(p["customer_id"]), actor="automation")  # verify, don't trust the click
                if not any(n["text"] == p["note"] for n in c["notes"]):
                    raise StepError("Clicked save but the change didn't stick")
                return {"via": "web UI"}
            if action == "send_message":
                ch = p["channel"].lstrip("#")
                await pg.goto(f"{BASE}/apps/chat?channel={ch}&actor=automation", wait_until="networkidle")
                box = await heal.locate(pg, "chat.input")
                await box.fill(p["text"])
                await box.press("Enter")
                await pg.wait_for_timeout(700)
                if not any(m["text"] == p["text"] for m in apps.list_chat("#" + ch)):
                    raise StepError("Sent, but the message never showed up")
                return {"via": "web UI"}
            raise StepError("No browser script for this action")
        finally:
            await b.close()


TIERS = {"api": _api, "app": _app, "browser": _browser}


# ---------------- run ----------------
def start(workflow_id: int, trigger: dict) -> int:
    wf = db.one("SELECT * FROM workflows WHERE id=?", (workflow_id,))
    spec = db.js(wf["spec"], {})
    steps = [{"id": s["id"], "label": s["label"], "app": s["app"], "action": s["action"], "status": "pending",
              "tier": None, "tried": [], "detail": "", "ms": 0} for s in spec["steps"]]
    # the run keeps the workflow as it was when it started, so editing it mid-run can't misalign steps
    return db.ex("INSERT INTO runs(workflow_id,status,trigger,vars,steps,started_at) VALUES (?,?,?,?,?,?)",
                 (workflow_id, "running", json.dumps(trigger), json.dumps({"email_id": trigger.get("email_id"), "_spec": spec}),
                  json.dumps(steps), db.now()))


def _load(run_id):
    r = db.one("SELECT * FROM runs WHERE id=?", (run_id,))
    r["vars"], r["steps"], r["trigger"] = db.js(r["vars"], {}), db.js(r["steps"], []), db.js(r["trigger"], {})
    return r


async def execute(run_id: int, resume_from: int = 0):
    """Safety net: whatever goes wrong, a run never stays stuck on 'running'."""
    try:
        await _execute(run_id, resume_from)
    except Exception as e:  # noqa: BLE001
        print("[engine] run", run_id, "crashed:", repr(e))
        run = _load(run_id)
        if run["status"] == "running":
            for rs in run["steps"]:
                if rs["status"] == "running":
                    rs.update(status="failed", detail=f"Unexpected error: {type(e).__name__}")
            run["status"], run["finished_at"] = "failed", db.now()
            _save_run(run)
            if _notify:
                try:
                    await _notify(run_id)
                except Exception:  # noqa: BLE001
                    pass


async def _execute(run_id: int, resume_from: int = 0):
    run = _load(run_id)
    wf = db.one("SELECT * FROM workflows WHERE id=?", (run["workflow_id"],))
    learned = db.js(wf["learned"], {})
    v = run["vars"]
    spec = v.get("_spec") or db.js(wf["spec"], {})
    run["status"] = "running"
    t0 = time.time()
    for i, step in enumerate(spec["steps"]):
        rs = run["steps"][i]
        if i < resume_from or rs["status"] in ("done", "skipped"):
            continue
        rs["status"] = "running"
        await _ping(run)
        await asyncio.sleep(0.55)  # human-visible pacing for the demo
        params = {k: render(x, v) for k, x in (step.get("params") or {}).items()}
        params.update((v.get("_edits") or {}).get(step["id"], {}))
        params.setdefault("email_id", v.get("email_id"))
        started = time.time()
        if not nl_edit.when_ok(step, v):  # a condition you added: this run doesn't need this step
            rs.update(status="skipped", tier=None, detail=f"Skipped: {step['when']['label'][:1].lower() + step['when']['label'][1:]}")
            await _ping(run)
            continue
        hctx = {"ui": learned.setdefault("ui", {}), "healed": []}
        heal.CTX.set(hctx)
        try:
            out = None
            if step["action"] in WRITES and learned.get("mode") == "preview" and not v.get("_approved"):
                raise NeedsUser("Check what I'm about to change", {"kind": "preview", "changes": _changes(spec, i, v)})
            if step["action"] == "manual":
                raise NeedsUser(f"Your turn: {step['label'][:1].lower() + step['label'][1:]}",
                                {"kind": "manual", "label": step["label"], "url": params.get("url"), "hint": params.get("hint")})
            if step["action"] == "find_customer":
                alias = (learned.get("aliases") or {}).get((params.get("email") or "").lower())
                if alias:
                    out = apps.get_customer(int(alias), actor="automation")
                    rs["tried"].append({"tier": "learned", "ok": True, "detail": "Remembered from last time"})
                    rs["tier"] = "learned"
            if out is None:
                for tier in step.get("tiers", ["api", "app", "browser"]):
                    fn = TIERS.get(tier)
                    if not fn:
                        continue
                    try:
                        out = await fn(step["action"], params, v)
                        rs["tried"].append({"tier": tier, "ok": True, "detail": TIER_LABEL[tier]})
                        rs["tier"] = tier
                        break
                    except Exception as e:  # noqa: BLE001 - any failure means: try the next tier
                        msg = str(e) if isinstance(e, StepError) else f"{type(e).__name__}: {str(e).splitlines()[0][:120]}"
                        rs["tried"].append({"tier": tier, "ok": False, "detail": msg})
                        await _ping(run)
                        await asyncio.sleep(0.35)
                if out is None:
                    raise StepError("Every automation method failed")
            _apply_output(step, out or {}, v, rs)
            if hctx["healed"]:
                rs["healed"] = hctx["healed"]
                for h in hctx["healed"]:
                    learned.setdefault("log", []).append(f"The app changed: {h['target']} is now {h['after']}. I adapted and remembered it.")
                db.ex("UPDATE workflows SET learned=? WHERE id=?", (json.dumps(learned), wf["id"]))
            if step["action"] == "update_customer":
                rs["undo"] = {"type": "crm_note", "customer_id": int(params["customer_id"]), "text": params["note"],
                              "attachment": params.get("attachment", "")}
            elif step["action"] == "send_message":
                rs["undo"] = {"type": "chat", "channel": params["channel"], "text": params["text"], "slack": bool((out or {}).get("slack"))}
            if step["action"] == "find_customer" and not v.get("customer_id"):
                dom = apps.find_by_domain(params.get("email"))
                raise NeedsUser(f"No customer in the CRM with {params.get('email')}",
                                {"suggested": dom["id"] if dom else None,
                                 "suggested_name": f"{dom['name']} ({dom['company']})" if dom else None,
                                 "email": params.get("email"), "name": v.get("customer_name")})
            rs["status"] = "done"
        except NeedsUser as nu:
            rs["status"] = "waiting"
            rs["detail"] = nu.reason
            run["status"] = "needs_you"
            run["note"] = json.dumps({"reason": nu.reason, "step": i, **nu.options})
            await _ping(run)
            return
        except StepError as e:
            rs["status"] = "failed"
            rs["detail"] = str(e)
            run["status"], run["finished_at"] = "failed", db.now()
            await _ping(run)
            _stats(wf, run, time.time() - t0, ok=False)
            return
        rs["ms"] = round((time.time() - started) * 1000)
        await _ping(run)
    run["status"], run["finished_at"], run["note"] = "done", db.now(), ""
    await _ping(run)
    _stats(wf, run, time.time() - t0, ok=True)
    _earn_trust(wf["id"], v)
    if v.get("email_id"):
        db.ex("UPDATE emails SET handled_by=? WHERE id=?", (run_id, v["email_id"]))


def _apply_output(step, out, v, rs):
    a = step["action"]
    if a == "read_email":
        v.update(customer_email=out.get("sender_email"), customer_name=out.get("sender_name"),
                 subject=out.get("subject"), attachment=out.get("attachment") or v.get("attachment"))
        rs["detail"] = f"{out.get('sender_name')} <{out.get('sender_email')}>: {out.get('subject')}"
    elif a == "download_attachment":
        v["attachment"] = out.get("attachment") or v.get("attachment")
        rs["detail"] = f"Saved {v['attachment']}"
    elif a == "find_customer":
        cid = out.get("id") or out.get("customer_id")
        v["customer_id"] = cid
        if cid:
            v["company"] = out.get("company")
            rs["detail"] = f"Found {out.get('name')} at {out.get('company')}"
    elif a == "update_customer":
        rs["detail"] = "Added the request note" + (f" and {v.get('attachment')}" if v.get("attachment") else "")
    elif a == "send_message":
        rs["detail"] = f"Posted in {step.get('params', {}).get('channel', '#support')}" + (" on Slack" if out.get("slack") else "")
    elif a == "open_page":
        rs["detail"] = f"Opened {out.get('title') or step['params'].get('url')}"
    elif a == "click":
        rs["detail"] = f"Downloaded {out['downloaded']}" if out.get("downloaded") else f"Clicked \"{out.get('clicked')}\""


WRITES = {"update_customer", "send_message"}
TRUST_AFTER = 2  # clean previews in a row before offering autopilot


def _changes(spec, from_i, v):
    """Everything this run is about to change, rendered with the real values, for the preview."""
    out = []
    for s in spec["steps"][from_i:]:
        if s["action"] not in WRITES or not nl_edit.when_ok(s, v):
            continue
        p = {k: render(x, v) for k, x in (s.get("params") or {}).items()}
        p.update((v.get("_edits") or {}).get(s["id"], {}))
        if s["action"] == "update_customer":
            c = apps.get_customer(int(p["customer_id"]), actor="automation") if p.get("customer_id") else None
            out.append({"step": s["id"], "app": "crm", "label": s["label"],
                        "where": f"{c['name']} · {c['company']}" if c else "Customer record",
                        "fields": [{"key": "note", "label": "Note to add", "value": p.get("note", "")},
                                   {"key": "attachment", "label": "Attachment", "value": p.get("attachment", ""), "readonly": True}],
                        "last_note": (c["notes"][0]["text"] if c and c["notes"] else None)})
        elif s["action"] == "send_message":
            out.append({"step": s["id"], "app": "chat", "label": s["label"], "where": p.get("channel", "#support"),
                        "fields": [{"key": "text", "label": "Message", "value": p.get("text", "")}]})
    return out


def _earn_trust(wid, v):
    """Earned autonomy: previews you approve without changes build trust; edits reset it."""
    if not v.get("_approved"):
        return
    wf = db.one("SELECT * FROM workflows WHERE id=?", (wid,))
    st, learned = db.js(wf["stats"], {}) or {}, db.js(wf["learned"], {}) or {}
    if v.get("_edits"):
        st["clean_streak"] = 0
        learned.setdefault("log", []).append("You corrected a preview, so I'll keep asking before I change things")
    else:
        st["clean_streak"] = st.get("clean_streak", 0) + 1
        if st["clean_streak"] >= TRUST_AFTER and learned.get("mode") == "preview":
            learned["suggest_auto"] = True
    db.ex("UPDATE workflows SET stats=?, learned=? WHERE id=?", (json.dumps(st), json.dumps(learned), wid))


async def undo(run_id: int):
    """Roll back everything a run changed, newest first. Undo also costs the workflow its autopilot."""
    run = _load(run_id)
    if run["status"] != "done":
        return False
    for rs in reversed(run["steps"]):
        u = rs.get("undo")
        if not u:
            continue
        ok = apps.remove_note(u["customer_id"], u["text"], u.get("attachment", "")) if u["type"] == "crm_note" \
            else apps.delete_chat(u["channel"], u["text"])
        if u.get("slack"):  # a Slack message can't be deleted by a webhook, so say it was reverted
            try:
                await asyncio.to_thread(connectors.slack_post, f"↩️ Undone by the user: the previous WorkFlowOS message in {u['channel']} was reverted.")
            except Exception:  # noqa: BLE001
                pass
        rs["undone"] = bool(ok)
    run["status"] = "undone"
    _save_run(run)
    if run["vars"].get("email_id"):
        db.ex("UPDATE emails SET handled_by=NULL WHERE id=?", (run["vars"]["email_id"],))
    wf = db.one("SELECT * FROM workflows WHERE id=?", (run["workflow_id"],))
    st, learned = db.js(wf["stats"], {}) or {}, db.js(wf["learned"], {}) or {}
    st["clean_streak"] = 0
    learned.pop("suggest_auto", None)
    msg = f"You undid run #{run_id}"
    if learned.get("mode") == "auto":
        learned["mode"] = "preview"
        msg += ", so I'm back to showing you changes first"
    learned.setdefault("log", []).append(msg)
    db.ex("UPDATE workflows SET stats=?, learned=? WHERE id=?", (json.dumps(st), json.dumps(learned), wf["id"]))
    if _notify:
        await _notify(run_id)
    return True


def _stats(wf, run, secs, ok):
    st = db.js(wf["stats"], {}) or {}
    pat = db.js(wf["pattern"], {}) or {}
    st["runs"] = st.get("runs", 0) + 1
    st["succeeded"] = st.get("succeeded", 0) + (1 if ok else 0)
    if ok:
        st["time_saved_sec"] = st.get("time_saved_sec", 0) + max(0, pat.get("avg_seconds", 0) - secs)
    st["last_run"] = db.now()
    db.ex("UPDATE workflows SET stats=? WHERE id=?", (json.dumps(st), wf["id"]))


async def resolve(run_id: int, customer_id: int | None = None, create: dict | None = None, remember=True,
                  edits: dict | None = None, cancel: bool = False):
    """User answered a 'needs you' question. Learn it and continue the run."""
    run = _load(run_id)
    if run["status"] != "needs_you":  # double-click or second tab: already answered
        return
    note = db.js(run["note"], {}) or {}
    wf = db.one("SELECT * FROM workflows WHERE id=?", (run["workflow_id"],))
    if note.get("kind") == "preview":
        step_i = int(note.get("step", 0))
        if cancel:
            run["steps"][step_i].update(status="skipped", detail="You cancelled before anything changed")
            run["status"], run["note"], run["finished_at"] = "cancelled", "", db.now()
            _save_run(run)
            if _notify:
                await _notify(run_id)
            return
        edits = {k: {f: val for f, val in fields.items() if f in ("note", "text")} for k, fields in (edits or {}).items()}
        orig = {c["step"]: {f["key"]: f["value"] for f in c["fields"]} for c in note.get("changes", [])}
        real = {k: {f: val for f, val in e.items() if orig.get(k, {}).get(f) != val} for k, e in edits.items()}
        real = {k: e for k, e in real.items() if e}
        run["vars"]["_approved"] = True
        if real:
            run["vars"]["_edits"] = real
        run["steps"][step_i].update(status="pending", detail="")
        run["status"], run["note"] = "running", ""
        _save_run(run)
        await execute(run_id, resume_from=step_i)
        return
    if note.get("kind") == "manual":  # a step only a person can do: they did it, carry on
        step_i = int(note.get("step", 0))
        run["steps"][step_i].update(status="done", tier="you", detail="You did this step")
        run["status"], run["note"] = "running", ""
        _save_run(run)
        await execute(run_id, resume_from=step_i + 1)
        return
    if create:
        customer_id = apps.create_customer(create.get("name") or note.get("name") or "New customer",
                                           create.get("email") or note.get("email"), create.get("company") or "")
    if not customer_id:
        return
    c = apps.get_customer(int(customer_id), actor="automation")
    run["vars"].update(customer_id=int(customer_id), company=c["company"])
    step_i = int(note.get("step", 0))
    run["steps"][step_i].update(status="done", tier="you", detail=f"You picked {c['name']} at {c['company']}")
    if remember and note.get("email"):
        learned = db.js(wf["learned"], {}) or {}
        learned.setdefault("aliases", {})[note["email"].lower()] = int(customer_id)
        learned.setdefault("log", []).append(f"{note['email']} belongs to {c['name']} ({c['company']})")
        db.ex("UPDATE workflows SET learned=? WHERE id=?", (json.dumps(learned), wf["id"]))
    run["status"], run["note"] = "running", ""
    _save_run(run)
    await execute(run_id, resume_from=step_i + 1)
