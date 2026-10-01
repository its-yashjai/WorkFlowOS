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
    """Parse a stored time. Old rows may carry a timezone or be malformed: read them as local time
    instead of letting one bad row stop discovery for good."""
    try:
        t = datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return datetime.min
    return t.astimezone().replace(tzinfo=None) if t.tzinfo else t


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


PASSIVE_WEB = "navigate"
WEB_ACTIONS = ("click", "form_submit", "download")
DEFAULT_IGNORE = "whatsapp, telegram, discord, spotify, youtube, netflix, primevideo, hotstar, instagram, facebook, twitter, x.com, reddit"


def ignore_list(st: dict | None = None) -> list[str]:
    """Apps and sites that are never part of a workflow (editable in Settings)."""
    raw = (st if st is not None else db.settings()).get("ignore_apps", DEFAULT_IGNORE)
    return [x.strip().lower().removesuffix(".exe") for x in re.split(r"[,\n]", raw or "") if x.strip()]


def _ignored(e: dict, ign: list[str]) -> bool:
    if not ign or e["app"] not in ("desktop", "web"):
        return False
    d = db.js(e.get("data"), {}) or {}
    if e["app"] == "desktop":
        proc = (d.get("process") or "").lower().removesuffix(".exe")
        return any(proc == x or proc.startswith(x) for x in ign if "." not in x)
    dom = (d.get("domain") or "").lower().replace("www.", "").split(":")[0]
    labels = dom.split(".")
    return any((dom == x or dom.endswith("." + x)) if "." in x else x in labels for x in ign)


def _where(e: dict) -> str | None:
    """Which place an event happened in, for measuring how long you stayed somewhere."""
    d = db.js(e.get("data"), {}) or {}
    if e["app"] == "desktop":
        proc = (d.get("process") or "").lower()
        return "browser" if proc in BROWSERS else "desktop:" + proc
    if e["app"] == "web":
        return "web:" + (d.get("domain") or "").replace("www.", "")
    if e["app"] == "files":
        return None  # a file landing in a folder doesn't say where you are
    return e["app"]


def _is_passive(e: dict) -> bool:
    """Only switching to an app or opening a page: looking, not doing."""
    return (e["app"] == "desktop" and e["action"] == "app_focus") or (e["app"] == "web" and e["action"] == PASSIVE_WEB)


def _stayed(sess: list[dict], i: int, min_dwell: float) -> bool:
    """A switch counts only if you did something there, or stayed long enough. A quick glance is ignored."""
    e = sess[i]
    here = _where(e)
    for nxt in sess[i + 1:]:
        w = _where(nxt)
        if w is None:
            continue
        if w == here:
            if nxt["app"] == "web" and nxt["action"] in WEB_ACTIONS:
                return True  # you clicked / submitted / downloaded on that page
            continue
        if here.startswith("web:") and w == "browser":
            continue  # the browser window coming to the front is still the same page
        return (ts(nxt["ts"]) - ts(e["ts"])).total_seconds() >= min_dwell
    return True  # last thing in the task: you stayed there until you stopped


def tokenize(sess: list[dict], st: dict | None = None):
    """Collapse consecutive duplicates; keep which events belong to each token.
    Quick glances at another app or tab, and apps on the never-work list, are dropped."""
    st = st if st is not None else db.settings()
    ign = ignore_list(st)
    try:
        min_dwell = float(st.get("min_dwell_sec", 10))
    except (TypeError, ValueError):
        min_dwell = 10.0
    toks, groups = [], []
    for i, e in enumerate(sess):
        t = token(e)
        if not t:
            continue
        if _ignored(e, ign):
            continue
        if _is_passive(e) and not _stayed(sess, i, min_dwell):
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


def shape(steps) -> tuple:
    """The steps as the generated workflow would show them. Two patterns with the same shape are the same
    workflow to a person (e.g. searching vs clicking the customer, or opening the channel before posting)."""
    out = []
    for t in steps:
        if t == "mail.open_email":
            k = "read"
        elif t in ("mail.download_attachment", "files.file_saved"):
            k = "download"
        elif t in ("crm.search", "crm.open_record"):
            k = "find"
        elif t == "crm.update_record":
            k = "update"
        elif t == "chat.post_message":
            k = "notify"
        elif t == "chat.open_channel":
            continue
        elif t.startswith("web.") and t.endswith(".download") and out and out[-1].startswith("web.") and ".click:" in out[-1]:
            continue  # the click before it already downloads the file
        else:
            k = t
        if k in ("download", "find") and k in out:
            continue
        out.append(k)
    return tuple(out)


def _just_looking(k: str) -> bool:
    """A step that is only 'was in this app / had this page open', with nothing done there."""
    return k.startswith("desktop.") or (k.startswith("web.") and not _does(k))


def clean_shape(steps) -> tuple:
    """The shape without the just-looking steps: what the routine is really made of."""
    return tuple(k for k in shape(steps) if not _just_looking(k))


def core(steps) -> tuple:
    """Only the steps that change or produce something."""
    return tuple(t for t in steps if _does(t))


def related(a, b) -> bool:
    """Same routine done slightly differently: one's steps sit inside the other's."""
    sa, sb = shape(a), shape(b)
    return _subseq(sa, sb) or _subseq(sb, sa)


def mine(min_support: int = 2, gap_min: float = 4.0) -> list[dict]:
    events = db.q("SELECT * FROM events ORDER BY ts, id")
    st = db.settings()
    tasks = []
    for s in sessions(events, gap_min):
        toks, groups = tokenize(s, st)
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
        occ = {}
        for ti, (toks, groups) in enumerate(tasks):
            m = match(c, toks)
            if m:
                occ[ti] = [e for k in range(m[0], m[-1] + 1) for e in groups[k]]
        if len(occ) >= min_support and len({_ctx(t) for t in c}) >= 2 and any(_does(t) for t in c):
            found[c] = occ
    # keep maximal patterns only
    keep = {}
    for c, occ in found.items():
        # a shorter pattern that lives inside a longer one (even with gaps) is the same routine, not a new one
        subsumed = any(len(o) > len(c) and len(found[o]) >= 0.6 * len(occ) and _subseq(c, o) for o in found)
        if not subsumed:
            keep[c] = dict(occ)
    # the same routine must never be suggested twice
    # (a) variants: the same steps, give or take an app or tab you had open on the way -> one routine,
    #     counted together. The cleanest version (fewest just-looking steps) is the one that is kept.
    def _looks(c):
        return sum(1 for k in shape(c) if _just_looking(k))
    merged = {}
    for c in sorted(keep, key=lambda c: (_looks(c), -len(keep[c]), len(c), c)):
        twin = next((m for m in merged if clean_shape(m) == clean_shape(c) and clean_shape(c)), None)
        if twin is None:
            merged[c] = keep[c]
        else:
            for ti, evs in keep[c].items():
                merged[twin].setdefault(ti, evs)
    # (b) pieces: a part of a longer routine, seen mostly in the same tasks, is that routine, not a new one
    final = {}
    for c in sorted(merged, key=lambda c: (-len(shape(c)), -len(merged[c]), c)):
        bigger = [f for f in final if len(shape(f)) > len(shape(c)) and _subseq(shape(c), shape(f))]
        covered = {ti for f in bigger for ti in final[f]} & set(merged[c])
        if bigger and len(covered) >= 0.6 * len(merged[c]):
            continue
        final[c] = merged[c]
    out = []
    for c, occ_by_task in final.items():
        occ = [occ_by_task[ti] for ti in sorted(occ_by_task)]
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


def _step_key(s: dict) -> tuple:
    p = s.get("params") or {}
    if s["app"] == "web":
        return (s["action"], p.get("url"), p.get("text"))
    if s["action"] == "manual":
        return (s["action"], s["label"])
    return (s["app"], s["action"])


def step_diff(cur: dict, new: dict) -> tuple[list[str], list[str]]:
    """Step labels the new way adds and removes, compared with the workflow as it is now.
    Steps you added by hand are yours: they are never reported as removed."""
    ck, nk = [_step_key(s) for s in cur["steps"]], [_step_key(s) for s in new["steps"]]
    added = [s["label"] for s in new["steps"] if _step_key(s) not in ck]
    removed = [s["label"] for s in cur["steps"] if _step_key(s) not in nk and not s.get("added_by_you")]
    return added, removed


def merge_spec(cur: dict, new: dict) -> dict:
    """Take the new order and steps, but keep everything you already customised on steps that stay,
    and keep the steps you added by hand (after the same step they followed before)."""
    pool = [s for s in cur["steps"] if not s.get("added_by_you")]
    used, steps = set(), []

    def put(st):
        st = json.loads(json.dumps(st))
        if st["id"] in used:
            n = 2
            while f"{st['id']}_{n}" in used:
                n += 1
            st["id"] = f"{st['id']}_{n}"
        used.add(st["id"])
        steps.append(st)

    for s in new["steps"]:
        k = _step_key(s)
        keep = next((x for x in pool if _step_key(x) == k), None)
        if keep:
            pool.remove(keep)
        put(keep or s)
    for i, s in enumerate(cur["steps"]):  # your own steps go back after the step they used to follow
        if not s.get("added_by_you"):
            continue
        prev = cur["steps"][i - 1]["id"] if i else None
        at = next((j + 1 for j, x in enumerate(steps) if x["id"] == prev), 0 if prev is None else len(steps))
        st = json.loads(json.dumps(s))
        while st["id"] in used:
            st["id"] += "_"
        used.add(st["id"])
        steps.insert(at, st)
    out = json.loads(json.dumps(cur))
    out["steps"] = steps
    ids = {s["id"] for s in steps}
    out["conditions"] = [c for c in new.get("conditions", []) if c["after"] in ids]
    out["trigger"], out["variables"], out["evidence"] = new["trigger"], new["variables"], new["evidence"]
    return out


def same_routine(a, b) -> bool:
    """Is pattern `a` the same routine as `b`, just done a little differently?
    Yes if they do the same actions (only the looking-around differs), or if one sits inside the other and
    they differ by at most two steps. A much shorter or longer sequence is a different routine."""
    if not related(a, b):
        return False
    return core(a) == core(b) or abs(len(shape(a)) - len(shape(b))) <= 2


def _find_related(p_steps, rows):
    """An existing workflow (any status) that is the same routine as this pattern."""
    best, best_n = None, -1
    for r in rows:
        r_steps = (db.js(r["pattern"], {}) or {}).get("steps") or []
        if r_steps and same_routine(p_steps, r_steps):
            n = len(set(shape(p_steps)) & set(shape(r_steps)))
            if n > best_n:
                best, best_n = r, n
    return best


def refresh() -> list[int]:
    """Mine patterns and upsert suggestions. Active/dismissed workflows keep their status.

    A routine is never suggested twice: a pattern that is the same routine as an existing workflow (in any
    status, dismissed included) never becomes a new card. If it shows you now do the routine differently,
    the existing workflow gets a *proposal* that you accept or decline. Nothing is changed without asking."""
    st = db.settings()
    pats = mine(int(st.get("min_support", 2)), float(st.get("session_gap_min", 4)))[:6]
    rows = db.q("SELECT * FROM workflows")
    by_sig = {r["signature"]: r for r in rows}
    ids, proposed = [], {}
    exact = {by_sig[signature(p["steps"])]["id"] for p in pats if signature(p["steps"]) in by_sig}
    for p in pats:
        sig = signature(p["steps"])
        spec = generate(p)
        pat = {"steps": p["steps"], "support": p["support"], "avg_seconds": p["avg_seconds"],
               "switches": p["switches"], "apps": p["apps"], "score": p["score"],
               "last_seen": p["occurrences"][-1][-1]["ts"]}
        row = by_sig.get(sig)
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
            continue
        rel = _find_related(p["steps"], rows)
        if rel:  # the same routine already has a card: never add a second one
            ids.append(rel["id"])
            if rel["status"] == "dismissed":
                continue  # you said no to this routine; a variation of it doesn't come back
            learned = db.js(rel["learned"], {}) or {}
            cur = db.js(rel["spec"], {}) or {}
            cur_pat = db.js(rel["pattern"], {}) or {}
            added, removed = step_diff(cur, spec)
            if not added and not removed:
                # same steps (only the looking-around differs): count it; the workflow itself is untouched
                if rel["id"] not in exact:
                    cur["evidence"] = spec["evidence"]
                    db.ex("UPDATE workflows SET spec=?, pattern=?, signature=?, updated_at=? WHERE id=?",
                          (json.dumps(cur), json.dumps(pat), sig, db.now(), rel["id"]))
                continue
            if sig in (learned.get("declined") or []):
                continue  # you already said "keep mine" to this variation
            if rel["id"] in exact and pat["last_seen"] <= (cur_pat.get("last_seen") or ""):
                continue  # an older way of doing it, not how you work now
            if rel["id"] not in proposed or pat["last_seen"] > proposed[rel["id"]]["last_seen"]:
                proposed[rel["id"]] = {"signature": sig, "pattern": pat, "spec": spec, "added": added, "removed": removed,
                                       "times_seen": p["support"], "last_seen": pat["last_seen"]}
            continue
        ids.append(db.ex("""INSERT INTO workflows(name,intent,status,spec,pattern,signature,created_at,updated_at)
                            VALUES (?,?,?,?,?,?,?,?)""",
                         (spec["name"], spec["description"], "suggested", json.dumps(spec), json.dumps(pat), sig,
                          db.now(), db.now())))
    # proposals: set the new ones, clear the ones that no longer apply
    for r in rows:
        learned = db.js(r["learned"], {}) or {}
        new_p, old_p = proposed.get(r["id"]), learned.get("proposal")
        if new_p:
            if not old_p or old_p.get("signature") != new_p["signature"] or old_p.get("times_seen") != new_p["times_seen"]:
                learned["proposal"] = new_p
                db.ex("UPDATE workflows SET learned=? WHERE id=?", (json.dumps(learned), r["id"]))
        elif old_p:
            learned.pop("proposal")
            db.ex("UPDATE workflows SET learned=? WHERE id=?", (json.dumps(learned), r["id"]))
    # a suggestion that no longer matches how you work (and that you never approved or edited) is withdrawn
    for w in db.q("SELECT id, spec FROM workflows WHERE status='suggested'"):
        if w["id"] not in ids and not (db.js(w["spec"], {}) or {}).get("edited"):
            db.ex("DELETE FROM workflows WHERE id=?", (w["id"],))
    return list(dict.fromkeys(ids))


def answer_proposal(wid: int, accept: bool) -> dict | None:
    """You answered 'you seem to do this differently now': update the workflow, or keep yours."""
    w = db.one("SELECT * FROM workflows WHERE id=?", (wid,))
    if not w:
        return None
    learned = db.js(w["learned"], {}) or {}
    prop = learned.pop("proposal", None)
    if not prop:
        return w
    declined = learned.setdefault("declined", [])
    if accept:
        cur = db.js(w["spec"], {}) or {}
        new = merge_spec(cur, prop["spec"])
        if cur.get("edited"):
            new["edited"] = True
        if w["signature"] not in declined:
            declined.append(w["signature"])  # the old way shouldn't be proposed back
        learned.setdefault("log", []).append("You updated it to match how you work now"
                                             + (": added " + ", ".join(prop["added"]) if prop["added"] else "")
                                             + (": removed " + ", ".join(prop["removed"]) if prop["removed"] else ""))
        taken = db.one("SELECT id FROM workflows WHERE signature=? AND id!=?", (prop["signature"], wid))
        db.ex("UPDATE workflows SET spec=?, pattern=?, learned=?, signature=?, updated_at=? WHERE id=?",
              (json.dumps(new), json.dumps(prop["pattern"]), json.dumps(learned),
               w["signature"] if taken else prop["signature"], db.now(), wid))
    else:
        if prop["signature"] not in declined:
            declined.append(prop["signature"])
        learned.setdefault("log", []).append("You kept your version when I noticed a different way of doing it")
        db.ex("UPDATE workflows SET learned=?, updated_at=? WHERE id=?", (json.dumps(learned), db.now(), wid))
    return db.one("SELECT * FROM workflows WHERE id=?", (wid,))
