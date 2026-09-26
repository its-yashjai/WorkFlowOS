"""Self-healing UI automation.

Browser scripts normally break the moment an app is redesigned: a test id disappears or "Save"
becomes "Update record". Here every UI target is described by what it *means* (role + intent words),
not only by a selector. When the recorded selector no longer matches, we scan the live page, score every
candidate element by meaning, pick the best one, and remember the new locator so the next run
goes straight to it.
"""
import contextvars
import re

# words that mean the same thing on a UI (small, auditable semantic lexicon)
CONCEPTS = [
    {"save", "update", "submit", "confirm", "apply", "store", "done", "log", "record"},
    {"note", "notes", "request", "comment", "details", "describe", "description", "summary", "ask", "asked"},
    {"attachment", "attach", "file", "document", "doc", "linked", "upload"},
    {"message", "msg", "write", "chat", "type", "reply", "say", "post", "compose"},
    {"search", "find", "lookup", "filter"},
    {"send", "post", "submit"},
]
STOP = {"the", "a", "an", "to", "of", "and", "or", "your", "this", "what", "did", "optional", "here", "for", "with",
        "name", "customer", "customers", "team"}

# the context a step's healing runs in: learned locators + what got healed during this step
CTX: contextvars.ContextVar[dict] = contextvars.ContextVar("heal_ctx", default={"ui": {}, "healed": []})

TARGETS = {
    "crm.note": {"testid": "crm-note", "role": "textbox", "words": ["note", "request"], "label": "CRM note field",
                 "was": "the note box"},
    "crm.attachment": {"testid": "crm-attachment", "role": "textbox", "words": ["attachment", "file"],
                       "label": "CRM attachment field", "was": "the attachment box"},
    "crm.save": {"testid": "crm-save", "role": "button", "words": ["save"], "label": "CRM Save button", "was": '"Save"'},
    "chat.input": {"testid": "chat-input", "role": "textbox", "words": ["message", "write"], "label": "Huddle message box",
                   "was": "the message box"},
}

_COLLECT = """(role) => {
  const sel = role === 'button' ? 'button, [role=button], input[type=submit], input[type=button], a'
                                : 'textarea, input:not([type]), input[type=text], input[type=search], [contenteditable=true]';
  return [...document.querySelectorAll(sel)].map((el, i) => {
    const r = el.getBoundingClientRect();
    const lab = el.id ? (document.querySelector(`label[for="${el.id}"]`)?.innerText || '') : (el.closest('label')?.innerText || '');
    return { i, visible: r.width > 0 && r.height > 0,
      text: (el.innerText || el.value || '').trim().slice(0, 60), aria: el.getAttribute('aria-label') || '',
      placeholder: el.getAttribute('placeholder') || '', name: el.getAttribute('name') || '', id: el.id || '', label: lab.slice(0, 60) };
  });
}"""


def _words(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]+", (s or "").lower()) if w not in STOP]


def _concepts(words) -> set:
    out = set()
    for w in words:
        hit = False
        for k, g in enumerate(CONCEPTS):
            if w in g or (len(w) > 4 and any(w.startswith(x) or x.startswith(w) for x in g if len(x) > 3)):
                out.add(k)
                hit = True
        if not hit:
            out.add(w)
    return out


def score(intent_words, cand: dict) -> float:
    want = _concepts(intent_words)
    have = _concepts(_words(" ".join([cand.get("text", ""), cand.get("aria", ""), cand.get("placeholder", ""),
                                       cand.get("name", ""), cand.get("id", "").replace("-", " "), cand.get("label", "")])))
    return len(want & have) / max(1, len(want))


def describe(c: dict) -> str:
    if c.get("text"):
        return f'"{c["text"]}"'
    if c.get("placeholder"):
        return f'the box "{c["placeholder"]}"'
    return c.get("aria") or c.get("name") or c.get("id") or "a similar element"


def _locator(pg, how: dict):
    if how["by"] == "role":
        return pg.get_by_role(how["role"], name=how["name"], exact=True)
    if how["by"] == "placeholder":
        return pg.get_by_placeholder(how["value"], exact=True)
    return pg.locator(how["value"])


async def locate(pg, key: str):
    """Find a UI target: remembered locator → original test id → heal by meaning."""
    t = TARGETS[key]
    ctx = CTX.get()
    how = ctx["ui"].get(key)
    if how:
        loc = _locator(pg, how)
        if await loc.count():
            return loc.first
    loc = pg.locator(f"[data-testid={t['testid']}]")
    if await loc.count():
        return loc.first
    cands = [c for c in await pg.evaluate(_COLLECT, t["role"]) if c["visible"]]
    ranked = sorted(cands, key=lambda c: -score(t["words"], c))
    if not ranked or score(t["words"], ranked[0]) < 0.5:
        from .engine import StepError
        raise StepError(f"{t['label']} is gone and nothing on the page means the same thing")
    best = ranked[0]
    if t["role"] == "button" and best["text"]:
        how = {"by": "role", "role": "button", "name": best["text"]}
    elif best["placeholder"]:
        how = {"by": "placeholder", "value": best["placeholder"]}
    elif best["id"]:
        how = {"by": "css", "value": f"#{best['id']}"}
    else:
        how = {"by": "css", "value": f"[name='{best['name']}']"}
    ctx["ui"][key] = how
    ctx["healed"].append({"target": t["label"], "before": t["was"], "after": describe(best),
                          "confidence": round(score(t["words"], best), 2)})
    return _locator(pg, how).first
