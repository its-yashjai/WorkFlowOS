"""Workflow Discovery Engine + AI Workflow Understanding + Workflow Generator.

events -> tasks (sessions split by idle gaps) -> step tokens -> repeated sequences
(frequency x length x cross-app transitions x time spent) -> intent + variables +
learned message templates -> structured workflow spec (trigger, steps, conditions).
"""
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timedelta

from . import db, llm

BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "chrome", "firefox", "safari"}
APP_LABEL = {"mail": "Mailbox", "crm": "Ledger CRM", "chat": "Huddle", "files": "Files", "desktop": "Desktop", "web": "Web"}
STEP_LABEL = {
    "mail.open_email": "Open customer email", "mail.download_attachment": "Download attachment",
    "files.file_saved": "Save file", "crm.search": "Search customer in CRM", "crm.open_record": "Open customer record",
    "crm.update_record": "Update customer record", "chat.open_channel": "Open team channel",
    "chat.post_message": "Notify the team",
}
NOISE = {"mail.view_inbox", "crm.view_list", "chat.view", "files.file_saved",
         "crm.search"}  # searching vs clicking the customer in the list are the same step: finding them


def ts(s):
    return datetime.fromisoformat(s)


def token(e: dict) -> str | None:
    app, action = e["app"], e["action"]
    d = db.js(e.get("data"), {}) or {}
    if app == "desktop" and action == "app_focus":
        proc = (d.get("process") or "").lower()
        if not proc or proc in BROWSERS:
            return None  # browser detail comes from the extension / app observer instead
        return f"desktop.{proc.replace('.exe', '')}"
    if app == "web":
        dom = (d.get("domain") or "").replace("www.", "")
        if action == "navigate":
            return f"web.{dom}"
        if action == "click":
            return f"web.{dom}.click:{(d.get('text') or '')[:24].strip().lower()}"
        return f"web.{dom}.{action}"
    t = f"{app}.{action}"
    return None if t in NOISE else t


def sessions(events: list[dict], gap_min: float) -> list[list[dict]]:
    out, cur, last = [], [], None
    for e in events:
        t = ts(e["ts"])
        if last and (t - last) > timedelta(minutes=gap_min) and cur:
            out.append(cur)
            cur = []
        cur.append(e)
        last = t
    if cur:
        out.append(cur)
    return out


def tokenize(sess: list[dict]):
    """Collapse consecutive duplicates; keep which events belong to each token."""
    toks, groups = [], []
    for e in sess:
        t = token(e)
        if not t:
            continue
        if toks and toks[-1] == t:
            groups[-1].append(e)
        else:
            toks.append(t)
            groups.append([e])
    return toks, groups


def match(pattern, toks, max_gap=2):
    """Find pattern as a subsequence of toks allowing up to max_gap extra tokens between steps."""
    for start in range(len(toks)):
        if toks[start] != pattern[0]:
            continue
        idx, pos, ok = [start], start, True
        for p in pattern[1:]:
            found = None
            for j in range(pos + 1, min(len(toks), pos + 2 + max_gap)):
                if toks[j] == p:
                    found = j
                    break
            if found is None:
                ok = False
                break
            idx.append(found)
            pos = found
        if ok:
            return idx
    return None


def _apps(pattern):
    return [p.split(".")[0] for p in pattern]


def _ctx(tok):
    """Which 'app' a step happens in: each website and desktop program counts separately."""
    parts = tok.split(".")
    if parts[0] == "web":
        return "web:" + _web_parts(tok)[0]
    if parts[0] == "desktop":
        return tok
    return parts[0]


ACTIONS = {"mail.download_attachment", "crm.update_record", "chat.post_message", "files.file_saved"}


def _does(tok: str) -> bool:
    """True for steps that change or produce something. Only-looking-around (opening records, switching apps)
    is never worth automating, so a routine must contain at least one of these."""
    if tok in ACTIONS:
        return True
    return tok.startswith("web.") and (".click:" in tok or tok.endswith((".form_submit", ".download")))


def _switches(pattern):
    a = [_ctx(t) for t in pattern]
    return sum(1 for x, y in zip(a, a[1:]) if x != y)


def mine(min_support: int = 2, gap_min: float = 4.0) -> list[dict]:
    events = db.q("SELECT * FROM events ORDER BY ts, id")
    tasks = []
    for s in sessions(events, gap_min):
        toks, groups = tokenize(s)
        if len(toks) >= 3:
            tasks.append((toks, groups))
    cands = set()
    for toks, _ in tasks:
        for n in range(3, min(9, len(toks) + 1)):
            for i in range(len(toks) - n + 1):
                c = tuple(toks[i:i + n])
                if len(set(c)) == len(c):  # no loops inside one pattern
                    cands.add(c)
    found = {}
    for c in cands:
        occ = []
        for toks, groups in tasks:
            m = match(c, toks)
            if m:
                evs = [e for k in range(m[0], m[-1] + 1) for e in groups[k]]
                occ.append(evs)
        if len(occ) >= min_support and len({_ctx(t) for t in c}) >= 2 and any(_does(t) for t in c):
            found[c] = occ
    # keep maximal patterns only
    keep = {}
    for c, occ in found.items():
        # a shorter pattern that lives inside a longer one (even with gaps) is the same routine, not a new one
        subsumed = any(len(o) > len(c) and len(found[o]) >= 0.6 * len(occ) and _subseq(c, o) for o in found)
        if not subsumed:
            keep[c] = occ
    out = []
    for c, occ in keep.items():
        durs = [(ts(o[-1]["ts"]) - ts(o[0]["ts"])).total_seconds() for o in occ]
        avg = sum(durs) / len(durs)
        score = len(occ) * len(c) * (1 + _switches(c)) * max(1.0, avg / 60)
        out.append({"steps": list(c), "occurrences": occ, "support": len(occ), "avg_seconds": round(avg),
                    "switches": _switches(c), "apps": list(dict.fromkeys(_apps(c))), "score": round(score, 1)})
    out.sort(key=lambda p: -p["score"])
    return out


def _subseq(small, big):
    it = iter(big)
    return all(x in it for x in small)


def _contains(big, small):
    n = len(small)
    return any(tuple(big[i:i + n]) == tuple(small) for i in range(len(big) - n + 1))


# ---------------- understanding: variables, templates, intent ----------------

def occurrence_vars(evs: list[dict]) -> dict:
    v = {}
    for e in evs:
        d = db.js(e["data"], {}) or {}
        k = f"{e['app']}.{e['action']}"
        if k == "mail.open_email":
            v.update(customer_email=d.get("from_email"), customer_name=d.get("from_name"), subject=d.get("subject"),
                     email_id=d.get("email_id"), has_attachment=bool(d.get("attachment")))
        elif k in ("mail.download_attachment", "files.file_saved"):
            v.setdefault("attachment", d.get("filename"))
        elif k == "crm.search":
            v["search"] = d.get("query")
        elif k == "crm.open_record":
            v.update(customer_id=d.get("customer_id"), company=d.get("company"))
        elif k == "crm.update_record":
            v.update(note=d.get("note"), attached=d.get("attachment"))
        elif k == "chat.post_message":
            v.update(channel=d.get("channel"), message=d.get("text"))
    return {k: x for k, x in v.items() if x not in (None, "")}


TEMPLATE_VARS = ["customer_email", "customer_name", "company", "subject", "attachment"]


def infer_template(samples: list[tuple[str, dict]]) -> tuple[str | None, float]:
    """Turn what the user typed into a reusable template by spotting known values in it."""
    temps = []
    for text, vars_ in samples:
        if not text:
            continue
        t = text
        for k in sorted(TEMPLATE_VARS, key=lambda k: -len(str(vars_.get(k) or ""))):
            val = str(vars_.get(k) or "")
            if len(val) >= 3 and val.lower() in t.lower():
                t = re.sub(re.escape(val), "{{" + k + "}}", t, flags=re.I)
        temps.append(t)
    if not temps:
        return None, 0.0
    best, n = Counter(temps).most_common(1)[0]
    return best, round(n / len(temps), 2)


PRETTY_PROC = {"excel": "Excel", "winword": "Word", "powerpnt": "PowerPoint", "outlook": "Outlook", "teams": "Teams",
               "ms-teams": "Teams", "slack": "Slack", "notepad": "Notepad", "explorer": "File Explorer", "acrord32": "Acrobat",
               "acrobat": "Acrobat", "code": "VS Code", "zoom": "Zoom", "whatsapp": "WhatsApp", "tally": "Tally"}


def _web_parts(tok):
    rest = tok[4:]
    if ".click:" in rest:
        dom, text = rest.split(".click:", 1)
        return dom, "click", text
    for a in ("form_submit", "download"):
        if rest.endswith("." + a):
            return rest[: -len(a) - 1], a, ""
    return rest, "navigate", ""


def pretty(tok: str) -> str:
    if tok in STEP_LABEL:
        return STEP_LABEL[tok]
    if tok.startswith("web."):
        dom, a, text = _web_parts(tok)
        return {"navigate": f"Open {dom}", "click": f'Click "{text}" on {dom}', "form_submit": f"Fill in and submit the form on {dom}",
                "download": f"Download the file from {dom}"}[a]
    if tok.startswith("desktop."):
        p = tok.split(".", 1)[1]
        return f"Work in {PRETTY_PROC.get(p, p.title())}"
    return tok


def _ctx_label(tok):
    if tok.startswith("web."):
        return _web_parts(tok)[0]
    if tok.startswith("desktop."):
        p = tok.split(".", 1)[1]
        return PRETTY_PROC.get(p, p.title())
    return APP_LABEL.get(tok.split(".")[0], tok.split(".")[0])


def intent_for(steps: list[str]) -> tuple[str, str]:
    s = set(steps)
    if {"mail.open_email", "crm.update_record", "chat.post_message"} <= s:
        name = "Process customer request"
    elif {"mail.open_email", "crm.update_record"} <= s:
        name = "Log customer email in CRM"
    elif {"mail.open_email", "chat.post_message"} <= s:
        name = "Forward email to the team"
    else:
        name = "Routine: " + " → ".join(dict.fromkeys(_ctx_label(x) for x in steps))
    labels = [pretty(x) for x in steps if x not in ("chat.open_channel",)]
    desc = (", ".join(l[:1].lower() + l[1:] for l in labels[:-1]) + (", then " if len(labels) > 1 else "")
            + labels[-1][:1].lower() + labels[-1][1:] + ".")
    desc = desc[:1].upper() + desc[1:]
    key = tuple(steps)
    if key in _NAMES:
        return _NAMES[key]
    if name.startswith("Routine:") and llm.enabled():  # known routines keep stable names; AI names the unfamiliar ones
        out = llm.chat_json("Name the business intent behind a repeated computer workflow. "
                            'Reply {"name": "<=5 words, verb first", "description": "one sentence"}',
                            "Steps: " + " -> ".join(labels))
        if out and out.get("name"):
            _NAMES[key] = (out["name"][:60], out.get("description", desc)[:200])
            return _NAMES[key]
    return name, desc


_NAMES: dict = {}  # AI names each routine once, not on every discovery pass


def generate(pattern: dict) -> dict:
    """Workflow Generator: trigger + steps + conditions + variables, learned from the occurrences."""
    occ = [occurrence_vars(o) for o in pattern["occurrences"]]
    steps_tok = pattern["steps"]
    name, desc = intent_for(steps_tok)
    note_t, note_c = infer_template([(o.get("note"), o) for o in occ])
    msg_t, msg_c = infer_template([(o.get("message"), o) for o in occ])
    channels = Counter(o.get("channel") for o in occ if o.get("channel"))
    channel = channels.most_common(1)[0][0] if channels else "#support"
    all_attach = all(o.get("has_attachment") for o in occ) if occ else False
    steps = []
    for t in steps_tok:
        if t == "mail.open_email":
            steps.append({"id": "read", "app": "mail", "action": "read_email", "label": "Read the email and identify the customer",
                          "out": ["customer_email", "customer_name", "subject"]})
        elif t in ("mail.download_attachment", "files.file_saved"):
            if not any(s["action"] == "download_attachment" for s in steps):
                steps.append({"id": "download", "app": "mail", "action": "download_attachment",
                              "label": "Download the attachment", "out": ["attachment"]})
        elif t in ("crm.search", "crm.open_record"):
            if not any(s["action"] == "find_customer" for s in steps):
                steps.append({"id": "find", "app": "crm", "action": "find_customer", "label": "Find the customer in the CRM",
                              "params": {"email": "{{customer_email}}"}, "out": ["customer_id", "company"]})
        elif t == "crm.update_record":
            steps.append({"id": "update", "app": "crm", "action": "update_customer",
                          "label": "Update the customer record with the request and attachment",
                          "params": {"customer_id": "{{customer_id}}", "note": note_t or "Request: {{subject}}",
                                     "attachment": "{{attachment}}"}, "learned_confidence": note_c})
        elif t == "chat.post_message":
            steps.append({"id": "notify", "app": "chat", "action": "send_message", "label": f"Notify the team in {channel}",
                          "params": {"channel": channel, "text": msg_t or "New request from {{customer_name}}: {{subject}}"},
                          "learned_confidence": msg_c})
        elif t == "chat.open_channel":
            continue
        elif t.startswith("web."):
            dom, a, text = _web_parts(t)
            ev = _last_event(pattern["occurrences"], t)
            d = (db.js(ev["data"], {}) or {}) if ev else {}
            url = (d.get("origin") or ("http://" if dom.split(":")[0] in ("localhost", "127.0.0.1") else "https://") + dom) + (d.get("path") or "/")
            sid = f"s{len(steps) + 1}"
            if a == "navigate":
                steps.append({"id": sid, "app": "web", "action": "open_page", "label": pretty(t), "params": {"url": url}, "tiers": ["browser"]})
            elif a == "click":
                steps.append({"id": sid, "app": "web", "action": "click", "label": f'Click "{d.get("text") or text}" on {dom}',
                              "params": {"url": url, "text": d.get("text") or text},
                              "tiers": ["browser"]})
            elif a == "download" and steps and steps[-1]["action"] == "click":
                continue  # the click before it already downloads the file
            else:
                fields = ", ".join(d.get("fields") or [])
                steps.append({"id": sid, "app": "web", "action": "manual", "label": pretty(t), "tiers": ["you"],
                              "params": {"url": url, "hint": f"Fields: {fields}" if fields else ""}})
        else:
            steps.append({"id": f"s{len(steps) + 1}", "app": t.split(".")[0], "action": "manual", "label": pretty(t),
                          "tiers": ["you"], "params": {}})
    for s in steps:
        s.setdefault("tiers", ["api", "app", "browser"])
    conditions = []
    if any(s["action"] == "find_customer" for s in steps):
        conditions.append({"after": "find", "if": "customer_not_found", "then": "stop_and_ask",
                           "label": "If the customer can't be found, stop and ask you"})
    trigger = {"type": "new_email", "app": "mail", "has_attachment": all_attach,
               "label": "New customer email" + (" with an attachment" if all_attach else "")} \
        if steps_tok[0] == "mail.open_email" else {"type": "manual", "label": "Run on demand"}
    return {"name": name, "description": desc, "trigger": trigger, "steps": steps, "conditions": conditions,
            "variables": sorted({k for o in occ for k in o if k in TEMPLATE_VARS + ["customer_id", "channel"]}),
            "evidence": {"times_seen": pattern["support"], "avg_manual_seconds": pattern["avg_seconds"],
                         "app_switches": pattern["switches"], "apps": pattern["apps"],
                         "examples": [{"customer": o.get("customer_name"), "subject": o.get("subject"),
                                       "message": o.get("message"), "note": o.get("note"), "when": oc[0]["ts"],
                                       "seconds": round((ts(oc[-1]["ts"]) - ts(oc[0]["ts"])).total_seconds())}
                                      for o, oc in list(zip(occ, pattern["occurrences"]))[-3:]]}}


def _last_event(occurrences, tok):
    for occ in reversed(occurrences):
        for e in reversed(occ):
            if token(e) == tok:
                return e
    return None


def signature(steps) -> str:
    return hashlib.md5("|".join(steps).encode()).hexdigest()[:12]


def refresh() -> list[int]:
    """Mine patterns and upsert suggestions. Active/dismissed workflows keep their status."""
    st = db.settings()
    pats = mine(int(st.get("min_support", 2)), float(st.get("session_gap_min", 4)))
    ids = []
    for p in pats[:6]:
        sig = signature(p["steps"])
        spec = generate(p)
        pat = {"steps": p["steps"], "support": p["support"], "avg_seconds": p["avg_seconds"],
               "switches": p["switches"], "apps": p["apps"], "score": p["score"],
               "last_seen": p["occurrences"][-1][-1]["ts"]}
        row = db.one("SELECT * FROM workflows WHERE signature=?", (sig,))
        if row:
            cur = db.js(row["spec"], {}) or {}
            if row["status"] == "suggested" and not cur.get("edited"):
                db.ex("UPDATE workflows SET spec=?, pattern=?, name=?, intent=?, updated_at=? WHERE id=?",
                      (json.dumps(spec), json.dumps(pat), spec["name"], spec["description"], db.now(), row["id"]))
            else:  # approved or hand-edited: keep the user's version, refresh only the evidence
                cur["evidence"] = spec["evidence"]
                db.ex("UPDATE workflows SET spec=?, pattern=?, updated_at=? WHERE id=?",
                      (json.dumps(cur), json.dumps(pat), db.now(), row["id"]))
            ids.append(row["id"])
        else:
            ids.append(db.ex("""INSERT INTO workflows(name,intent,status,spec,pattern,signature,created_at,updated_at)
                                VALUES (?,?,?,?,?,?,?,?)""",
                             (spec["name"], spec["description"], "suggested", json.dumps(spec), json.dumps(pat), sig,
                              db.now(), db.now())))
    # a suggestion that no longer matches how you work (and that you never approved or edited) is withdrawn
    for w in db.q("SELECT id, spec FROM workflows WHERE status='suggested'"):
        if w["id"] not in ids and not (db.js(w["spec"], {}) or {}).get("edited"):
            db.ex("DELETE FROM workflows WHERE id=?", (w["id"],))
    return ids
