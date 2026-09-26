"""Change a workflow by saying it.

"only notify #finance if the attachment is an invoice, and tag Priya" becomes a list of small, typed
operations. The AI (on-device first, see llm.py) only ever proposes operations from this fixed vocabulary;
every one is validated against the real workflow and turned into a readable diff for you to approve.
If no AI model is running, a built-in parser handles the common phrasings, so this always works.
"""
import copy
import json
import re
import time

from . import llm

VARS = {"attachment": "the attachment", "subject": "the email subject", "customer_name": "the sender's name",
        "customer_email": "the sender's email", "company": "the company"}
OPS = {"set_channel", "set_text", "mention", "add_condition", "remove_condition", "remove_step", "add_notify"}
EXPAND = {"invoice": ["invoice", "inv-", "inv_"], "invoices": ["invoice", "inv-", "inv_"],
          "purchase order": ["purchase order", "po-", "po_"], "po": ["purchase order", "po-", "po_"],
          "w-9": ["w-9", "w9"], "w9": ["w-9", "w9"], "tax": ["tax", "w-9", "w9"], "contract": ["contract", "agreement"]}

SYSTEM = """You edit an automation workflow. Turn the user's request into operations.
Allowed operations (use step ids from the list you are given):
{"op":"set_channel","step":ID,"channel":"#name"}                 - post to a different chat channel
{"op":"set_text","step":ID,"value":TEXT}                          - new message / note text; may use {{customer_name}} {{company}} {{subject}} {{attachment}}
{"op":"mention","step":ID,"who":"Name"}                           - tag a person in the message
{"op":"add_condition","step":ID,"var":VAR,"contains":["word"],"negate":false} - only run the step if VAR contains any word (negate:true = unless)
{"op":"remove_condition","step":ID}
{"op":"remove_step","step":ID}                                    - stop doing that step
{"op":"add_notify","channel":"#name","text":TEXT}                 - ALSO post in another channel
VAR is one of: attachment, subject, customer_name, customer_email, company.
Reply as {"ops":[...],"summary":"one short sentence"}. Only use what the user asked for."""

# worked example, sent as a separate earlier turn; deliberately unlike the demo so it can't be confused with it
EXAMPLE_IN = ('Steps: [{"id":"notify","action":"send_message","label":"Notify the team in #support"}]\n'
              'Request: post in #ops only when the subject mentions outage, and tag Meena')
EXAMPLE_OUT = ('{"ops":[{"op":"set_channel","step":"notify","channel":"#ops"},'
               '{"op":"add_condition","step":"notify","var":"subject","contains":["outage"],"negate":false},'
               '{"op":"mention","step":"notify","who":"Meena"}],"summary":"Outage emails go to #ops with Meena tagged."}')


def _steps_brief(spec):
    return [{"id": s["id"], "action": s["action"], "label": s["label"]} for s in spec["steps"]]


def _step_id(spec, ref, default_action=None):
    ids = {s["id"] for s in spec["steps"]}
    if ref in ids:
        return ref
    r = (ref or "").lower()
    for s in spec["steps"]:
        if r and (r in s["label"].lower() or r in s["action"]):
            return s["id"]
    for key, action in (("notif", "send_message"), ("chat", "send_message"), ("message", "send_message"), ("post", "send_message"),
                        ("crm", "update_customer"), ("note", "update_customer"), ("update", "update_customer"), ("record", "update_customer")):
        if key in r:
            return next((s["id"] for s in spec["steps"] if s["action"] == action), None)
    if default_action:
        return next((s["id"] for s in spec["steps"] if s["action"] == default_action), None)
    return None


# ---------------- rules fallback ----------------
def rules(text: str, spec) -> list[dict]:
    t, low = text.strip(), text.lower()
    ops = []
    notify = _step_id(spec, "", "send_message")
    update = _step_id(spec, "", "update_customer")
    chans = re.findall(r"#([a-z0-9][\w-]*)", low)
    if chans and notify:
        if re.search(r"\b(also|as well|too|additionally)\b", low):
            ops += [{"op": "add_notify", "channel": "#" + c} for c in chans]
        else:
            ops.append({"op": "set_channel", "step": notify, "channel": "#" + chans[0]})
            ops += [{"op": "add_notify", "channel": "#" + c} for c in chans[1:]]
    for who in re.findall(r"(?:tag|mention|cc|ping|loop in|notify)\s+@?([A-Z][a-zA-Z]+)", t) + re.findall(r"@([A-Za-z]+)", t):
        if notify and who.lower() not in ("the", "team") and not any(o.get("who") == who for o in ops):
            ops.append({"op": "mention", "step": notify, "who": who})
    m = re.search(r"\b(only|unless)\b(.*?)\b(?:if|when)?\s*(?:the\s+)?(attachment|file|document|subject|email|sender|customer|company)\b"
                  r"[^,.]*?\b(?:is|are|contains?|mentions?|has|includes?|looks like|says|about)\b\s+(?:an?\s+|the\s+)?([\w\- ]+?)"
                  r"(?=\s*(?:,|\.|;|$|\band\b|\bthen\b))", low)
    if m:
        which = m.group(2) + " " + low[:m.start()]
        step = update if re.search(r"crm|record|note|update", which) and not re.search(r"notif|post|message|chat|#", which) else notify
        var = {"attachment": "attachment", "file": "attachment", "document": "attachment", "subject": "subject",
               "email": "subject", "sender": "customer_email", "customer": "customer_name", "company": "company"}[m.group(3)]
        word = m.group(4).strip()
        if step:
            ops.append({"op": "add_condition", "step": step, "var": var, "contains": [word], "negate": m.group(1) == "unless"})
    var_of = {"attachment": "attachment", "file": "attachment", "document": "attachment", "subject": "subject",
              "email": "subject", "sender": "customer_email", "customer": "customer_name", "company": "company"}
    if not m:  # "skip the chat message when the subject mentions test" / "don't notify if the file is a W-9"
        m2 = re.search(r"\b(skip|don'?t|do not|never)\b(.*?)\b(?:when|if)\s+(?:the\s+)?(attachment|file|document|subject|email|sender|customer|company)\b"
                       r"[^,.]*?\b(?:is|are|contains?|mentions?|has|includes?|says|about)\b\s+(?:an?\s+|the\s+)?([\w\- ]+?)"
                       r"(?=\s*(?:,|\.|;|$|\band\b|\bthen\b))", low)
        if m2:
            which = m2.group(2)
            step = update if re.search(r"crm|record|note|update", which) and not re.search(r"notif|post|message|chat|#", which) else notify
            if step:
                ops.append({"op": "add_condition", "step": step, "var": var_of[m2.group(3)], "contains": [m2.group(4).strip()], "negate": True})
                m = m2
    if not m:  # "only notify #finance for invoices"
        m3 = re.search(r"\bonly\b.*?\bfor\s+(?:an?\s+|the\s+)?(invoices?|purchase orders?|pos|contracts?|w-?9s?|tax forms?|refunds?)\b", low)
        if m3 and notify:
            word = m3.group(1)
            word = word[:-1] if word.endswith("s") and word[:-1] in EXPAND else word
            var = "subject" if word.startswith("refund") else "attachment"
            ops.append({"op": "add_condition", "step": notify, "var": var, "contains": [word.rstrip("s") if var == "subject" else word], "negate": False})
            m = m3
    if notify and re.search(r"\b(don'?t|do not|stop|no longer|never)\b.{0,20}\b(notify|post|message|ping)", low) and not m:
        ops.append({"op": "remove_step", "step": notify})
    q = re.search(r"(?:say|saying|message|text|write)\s*[:\-]?\s*[\"“'](.+?)[\"”']", t)
    if q and notify:
        ops.append({"op": "set_text", "step": notify, "value": q.group(1)})
    if re.search(r"\b(always|remove the condition|every time|for all)\b", low) and notify and not m:
        ops.append({"op": "remove_condition", "step": notify})
    return ops


# ---------------- validation + apply ----------------
def _clean(op, spec):
    if not isinstance(op, dict) or op.get("op") not in OPS:
        return None
    o = dict(op)
    if o["op"] != "add_notify":
        default = "send_message" if o["op"] in ("set_channel", "mention") else None
        o["step"] = _step_id(spec, str(o.get("step", "")), default)
        if not o["step"]:
            return None
    if o["op"] in ("set_channel", "add_notify"):
        ch = str(o.get("channel", "")).strip().lower().replace(" ", "-")
        if not re.fullmatch(r"#?[a-z0-9][\w-]{0,30}", ch):
            return None
        o["channel"] = ch if ch.startswith("#") else "#" + ch
    if o["op"] == "add_condition":
        if o.get("var") not in VARS:
            o["var"] = "attachment" if "attach" in str(o.get("var", "")) or "file" in str(o.get("var", "")) else \
                "subject" if "subject" in str(o.get("var", "")) or "email" in str(o.get("var", "")) else None
        words = o.get("contains") or o.get("value") or []
        words = [words] if isinstance(words, str) else words
        words = [str(w).strip().lower() for w in words if str(w).strip()][:5]
        if not o["var"] or not words:
            return None
        o["contains"], o["negate"] = words, bool(o.get("negate"))
    if o["op"] == "mention":
        who = re.sub(r"[^A-Za-z .]", "", str(o.get("who", ""))).strip()[:30]
        if not who:
            return None
        o["who"] = who
    if o["op"] == "set_text" and not str(o.get("value", "")).strip():
        return None
    return o


def _step(spec, sid):
    return next((s for s in spec["steps"] if s["id"] == sid), None)


def cond_label(w):
    words = " or ".join(f'"{x}"' for x in w["show"])
    return f"{'Unless' if w.get('negate') else 'Only if'} {VARS[w['var']]} mentions {words}"


def apply(spec, ops):
    new = copy.deepcopy(spec)
    new.pop("edited", None)
    changes = []
    for o in ops:
        if o["op"] == "add_notify":
            base = next((s for s in new["steps"] if s["action"] == "send_message"), None)
            if not base:
                continue
            n = copy.deepcopy(base)
            n["id"] = f"notify{sum(1 for s in new['steps'] if s['action'] == 'send_message') + 1}"
            n.pop("when", None)
            n["params"]["channel"] = o["channel"]
            if o.get("text"):
                n["params"]["text"] = o["text"]
            n["label"] = f"Notify the team in {o['channel']}"
            new["steps"].append(n)
            changes.append({"kind": "add", "text": f"Also post in {o['channel']}"})
            continue
        s = _step(new, o["step"])
        if s is None:  # e.g. the AI removed this step earlier in the same answer
            continue
        if o["op"] == "set_channel":
            old = s["params"].get("channel")
            s["params"]["channel"] = o["channel"]
            s["label"] = f"Notify the team in {o['channel']}"
            changes.append({"kind": "change", "text": f"Post in {o['channel']} instead of {old}"})
        elif o["op"] == "set_text":
            key = "text" if s["action"] == "send_message" else "note"
            s["params"][key] = o["value"]
            changes.append({"kind": "change", "text": f"{s['label']}: new wording \"{o['value']}\""})
        elif o["op"] == "mention":
            key = "text" if s["action"] == "send_message" else "note"
            if f"@{o['who']}" not in s["params"].get(key, ""):
                s["params"][key] = (s["params"].get(key, "") + f" @{o['who']}").strip()
            changes.append({"kind": "add", "text": f"Tag @{o['who']} in the message"})
        elif o["op"] == "add_condition":
            match = sorted({x for w in o["contains"] for x in EXPAND.get(w, [w])})
            s["when"] = {"var": o["var"], "any": match, "show": o["contains"], "negate": o["negate"]}
            s["when"]["label"] = cond_label(s["when"])
            ws = " or ".join(f'"{x}"' for x in o["contains"])
            changes.append({"kind": "add", "text": f"{s['label']}: skip it when {VARS[o['var']]} mentions {ws}" if o["negate"]
                            else f"{s['label']}: only when {VARS[o['var']]} mentions {ws}, otherwise skip it"})
        elif o["op"] == "remove_condition" and s.get("when"):
            changes.append({"kind": "remove", "text": f"{s['label']}: {s['when']['label'][:1].lower() + s['when']['label'][1:]}"})
            s.pop("when")
        elif o["op"] == "remove_step":
            if s["action"] in ("read_email", "find_customer"):
                continue  # the workflow can't work without these
            new["steps"] = [x for x in new["steps"] if x["id"] != s["id"]]
            changes.append({"kind": "remove", "text": s["label"]})
    return new, changes


def _grounded(o, text: str) -> bool:
    """Only keep what the person actually asked for: channels, names and keywords must appear in their words."""
    low = text.lower()
    words = set(re.findall(r"[a-z0-9]+", low))
    near = lambda w: w in low or w.rstrip("s") in low or (len(w) > 4 and any(x.startswith(w[:5]) for x in words))
    if o["op"] in ("set_channel", "add_notify"):
        return o["channel"].lstrip("#") in low
    if o["op"] == "mention":
        return o["who"].lower() in low
    if o["op"] == "add_condition":
        return all(all(near(p) for p in w.split()) for w in o["contains"])
    if o["op"] == "set_text":
        vw = [w for w in re.findall(r"[a-z]+", re.sub(r"\{\{.*?\}\}", "", o["value"].lower())) if len(w) > 3]
        return not vw or sum(w in low for w in vw) / len(vw) >= 0.5
    if o["op"] in ("remove_step", "remove_condition"):
        return bool(re.search(r"\b(remove|stop|don'?t|do not|skip|never|no longer|always|every time|drop)\b", low))
    return False


def _same(a, b):
    if a["op"] != b["op"]:
        return False
    if a["op"] == "add_notify":
        return a["channel"] == b["channel"]
    if a["op"] == "mention":
        return a["who"].lower() == b["who"].lower()
    return a.get("step") == b.get("step")


def _normalize(o, spec, text):
    """Small models reach for 'add another notify' when the person meant 'move it'. Only add when they said also/too."""
    if not o or o["op"] != "add_notify":
        return o
    if not re.search(r"\b(also|as well|too|additionally|both|cc|in addition)\b", text.lower()):
        main = _step_id(spec, "", "send_message")
        return {"op": "set_channel", "step": main, "channel": o["channel"]} if main else None
    if o.get("text") and not _grounded({"op": "set_text", "value": o["text"]}, text):
        o = {k: v for k, v in o.items() if k != "text"}
    return o


def _conflicts(a, b):
    if _same(a, b):
        return True
    chan = ("set_channel", "add_notify")
    if a["op"] in chan and b["op"] in chan and a["channel"] == b["channel"]:
        return True
    if a["op"] == b["op"] and a["op"] in ("set_channel", "add_condition", "set_text") and a.get("step") == b.get("step"):
        return True
    return False


def propose(spec, text: str) -> dict:
    t0 = time.time()
    st = llm.status()
    ai_ops, used, note = [], "rules", ""
    rule_ops = [c for c in (_clean(o, spec) for o in rules(text, spec)) if c]
    if st["engine"] != "rules":
        out = llm.chat_json(SYSTEM, f"Steps: {json.dumps(_steps_brief(spec))}\nRequest: {text}", max_tokens=500,
                            shots=[(EXAMPLE_IN, EXAMPLE_OUT)])
        raw = [c for c in (_normalize(_clean(o, spec), spec, text) for o in ((out or {}).get("ops") or [])) if c]
        ai_ops = [o for o in raw if _grounded(o, text)]
        dropped = len(raw) - len(ai_ops)
        if ai_ops:
            used = st["engine"]
            if dropped:
                note = f"Ignored {dropped} suggestion{'s' if dropped > 1 else ''} that went beyond what you asked."
        else:
            note = "The AI's answer didn't match your request, so I used the built-in parser."
    # the deterministic parser's reading wins; the AI adds only what the parser didn't catch and doesn't contradict
    ops = list(rule_ops)
    for o in ai_ops:
        if not any(_conflicts(o, r) for r in ops):
            ops.append(o)
    new, changes = apply(spec, ops)
    return {"ops": ops, "changes": changes, "spec": new, "engine": used, "model": st["model"] if used != "rules" else None,
            "local": used != "groq", "ms": round((time.time() - t0) * 1000), "note": note,
            "understood": bool(changes)}


def when_ok(step, v) -> bool:
    w = step.get("when")
    if not w:
        return True
    val = str(v.get(w["var"]) or "").lower()
    hit = any(x in val for x in w.get("any", []))
    return not hit if w.get("negate") else hit
