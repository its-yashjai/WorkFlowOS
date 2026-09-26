"""The AI layer. Private by default.

Order: local Ollama model on this machine → Groq (only if you allow cloud AI and set a key) → None
(callers then fall back to built-in rules). With "Local AI only" on (the default), nothing about your
activity ever leaves this computer.
"""
import json
import os
import re
import time

import httpx

GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
PREFERRED = ["qwen2.5:3b", "qwen2.5:7b", "llama3.2:3b", "llama3.1:8b", "qwen2.5:1.5b", "llama3.2:1b", "gemma2:2b", "phi3:mini"]
_client, _key = None, None
_ollama = {"checked": 0.0, "model": None}


def _settings():
    from . import db
    return db.settings()


def key() -> str:
    return _settings().get("groq_key", "").strip() or os.environ.get("GROQ_API_KEY", "").strip()


def local_only() -> bool:
    return _settings().get("ai_local_only", "1") == "1"


def ollama_model() -> str | None:
    """Which local model to use, if Ollama is running (checked at most every 15 s)."""
    if time.time() - _ollama["checked"] < 15:
        return _ollama["model"]
    _ollama["checked"] = time.time()
    try:
        tags = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=0.8).json().get("models", [])
        names = [t["name"] for t in tags]
        want = _settings().get("ollama_model", "").strip()
        pick = want if want in names else next((p for p in PREFERRED if p in names), names[0] if names else None)
        _ollama["model"] = pick
    except Exception:
        _ollama["model"] = None
    return _ollama["model"]


def status() -> dict:
    m = ollama_model()
    if m:
        return {"engine": "ollama", "model": m, "local": True, "label": f"On-device AI · {m}"}
    if key() and not local_only():
        return {"engine": "groq", "model": GROQ_MODEL, "local": False, "label": f"Cloud AI · Groq {GROQ_MODEL}"}
    return {"engine": "rules", "model": None, "local": True, "label": "Built-in rules (no AI model running)"}


def enabled() -> bool:
    return status()["engine"] != "rules"


def chat(system: str, user: str, temperature: float = 0.1, max_tokens: int = 400, json_mode: bool = False,
         shots: list[tuple[str, str]] | None = None) -> str | None:
    """`shots` are worked examples sent as earlier turns of the conversation (small models copy inline examples)."""
    global _client, _key
    st = status()
    msgs = [{"role": "system", "content": system}]
    for q, a in shots or []:
        msgs += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
    msgs.append({"role": "user", "content": user})
    try:
        if st["engine"] == "ollama":
            body = {"model": st["model"], "stream": False, "options": {"temperature": temperature, "num_predict": max_tokens},
                    "messages": msgs}
            if json_mode:
                body["format"] = "json"
            r = httpx.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=90)
            return r.json()["message"]["content"]
        if st["engine"] == "groq":
            if _client is None or _key != key():
                from groq import Groq
                _client, _key = Groq(api_key=key()), key()
            kw = {"response_format": {"type": "json_object"}} if json_mode else {}
            r = _client.chat.completions.create(model=GROQ_MODEL, temperature=temperature, max_tokens=max_tokens,
                                                messages=msgs, **kw)
            return r.choices[0].message.content
    except Exception as e:  # noqa: BLE001
        print("[llm] failed:", e)
    return None


def chat_json(system: str, user: str, max_tokens: int = 400, shots: list[tuple[str, str]] | None = None) -> dict | None:
    t = chat(system + " Respond with ONLY valid JSON.", user, max_tokens=max_tokens, json_mode=True, shots=shots)
    m = re.search(r"\{.*\}", t or "", re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None
