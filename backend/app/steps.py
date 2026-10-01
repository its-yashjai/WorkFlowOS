"""Edit a workflow by hand: remove a step, or add one in between.

Every edit is validated against the workflow, so it can never be left in a state the engine can't run:
a step can't be removed while a later step still needs what it produces, and a new step must be one of the
kinds the automation engine knows how to do.
"""
import copy
import re

KINDS = {
    "notify": "Post a message in a team channel",
    "crm_note": "Add a note to the customer record",
    "open_page": "Open a web page",
    "click": "Click a button or link on a web page",
    "manual": "A step you do yourself, then it carries on",
}
VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")
# what each kind of step hands to the steps after it
PROVIDES = {"read_email": {"customer_email", "customer_name", "subject", "attachment"},
            "download_attachment": {"attachment"}, "find_customer": {"customer_id", "company"}}


class EditError(ValueError):
    pass


def _needs(step: dict) -> set:
    """Variables a step reads: {{placeholders}} in its settings and the variable its condition checks."""
    need = set()
    for v in (step.get("params") or {}).values():
        if isinstance(v, str):
            need |= set(VAR.findall(v))
    if step.get("when"):
        need.add(step["when"]["var"])
    return need


def _index(spec, sid):
    i = next((k for k, s in enumerate(spec["steps"]) if s["id"] == sid), None)
    if i is None:
        raise EditError("That step isn't in this workflow any more. Refresh the page.")
    return i


def delete_step(spec: dict, step_id: str) -> tuple[dict, str]:
    new = copy.deepcopy(spec)
    i = _index(new, step_id)
    gone = new["steps"][i]
    if len(new["steps"]) == 1:
        raise EditError("A workflow needs at least one step.")
    rest = new["steps"][:i] + new["steps"][i + 1:]
    gives = PROVIDES.get(gone["action"], set())
    for k, s in enumerate(rest):
        if k < i:
            continue  # steps before it can't depend on it
        still = set().union(*[PROVIDES.get(x["action"], set()) for x in rest[:k]]) if k else set()
        lost = (_needs(s) & gives) - still
        if lost:
            what = ", ".join(sorted(v.replace("_", " ") for v in lost))
            raise EditError(f'"{s["label"]}" needs the {what} from this step. Remove that step first.')
    new["steps"] = rest
    new["conditions"] = [c for c in new.get("conditions", []) if c["after"] != step_id]
    return new, f'Removed "{gone["label"]}"'


def _new_id(spec, base):
    ids = {s["id"] for s in spec["steps"]}
    if base not in ids:
        return base
    n = 2
    while f"{base}{n}" in ids:
        n += 1
    return f"{base}{n}"


def _url(u: str) -> str:
    u = (u or "").strip()
    if not re.fullmatch(r"https?://[^\s]{3,300}", u):
        raise EditError("Enter a full web address that starts with http:// or https://")
    return u


def add_step(spec: dict, after: str | None, kind: str, params: dict | None) -> tuple[dict, str]:
    """Insert a step after `after` (None = make it the first step)."""
    if kind not in KINDS:
        raise EditError("I don't know that kind of step.")
    p = {k: str(v).strip() for k, v in (params or {}).items() if v is not None}
    new = copy.deepcopy(spec)
    at = 0 if after is None else _index(new, after) + 1
    before = new["steps"][:at]
    have = set().union(*[PROVIDES.get(x["action"], set()) for x in before]) if before else set()
    if kind == "notify":
        ch = p.get("channel", "").lower().replace(" ", "-")
        if not re.fullmatch(r"#?[a-z0-9][\w-]{0,30}", ch):
            raise EditError("Enter a channel name like #support.")
        ch = ch if ch.startswith("#") else "#" + ch
        if not p.get("text"):
            raise EditError("Write the message to post.")
        step = {"id": _new_id(new, "notify"), "app": "chat", "action": "send_message", "label": f"Notify the team in {ch}",
                "params": {"channel": ch, "text": p["text"]}, "tiers": ["api", "app", "browser"]}
    elif kind == "crm_note":
        if "customer_id" not in have:
            raise EditError('A CRM note needs a customer. Put it after "Find the customer in the CRM".')
        if not p.get("note"):
            raise EditError("Write the note to add.")
        step = {"id": _new_id(new, "update"), "app": "crm", "action": "update_customer", "label": "Add a note to the customer record",
                "params": {"customer_id": "{{customer_id}}", "note": p["note"], "attachment": ""}, "tiers": ["api", "app", "browser"]}
    elif kind == "open_page":
        url = _url(p.get("url"))
        host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
        step = {"id": _new_id(new, "page"), "app": "web", "action": "open_page", "label": f"Open {host}",
                "params": {"url": url}, "tiers": ["browser"]}
    elif kind == "click":
        url = _url(p.get("url"))
        if not p.get("text"):
            raise EditError("Enter the text on the button or link to click.")
        host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
        step = {"id": _new_id(new, "click"), "app": "web", "action": "click", "label": f'Click "{p["text"][:40]}" on {host}',
                "params": {"url": url, "text": p["text"][:80]}, "tiers": ["browser"]}
    else:
        if not p.get("label"):
            raise EditError("Describe what you do in this step.")
        step = {"id": _new_id(new, "you"), "app": "desktop", "action": "manual", "label": p["label"][:80],
                "params": {"hint": p.get("hint", "")[:160]}, "tiers": ["you"]}
    missing = _needs(step) - have - {"customer_id"}
    if missing:
        what = ", ".join(sorted(v.replace("_", " ") for v in missing))
        raise EditError(f"This step uses the {what}, which isn't known yet at this point. Move it further down.")
    step["added_by_you"] = True
    new["steps"].insert(at, step)
    return new, f'Added "{step["label"]}"'
