"""SQLite storage for WorkFlowOS. One file, zero setup."""
import json
import os
import sqlite3
import threading
from datetime import datetime

DB_PATH = os.environ.get("WFOS_DB", os.path.join(os.path.dirname(__file__), "..", "workflowos.db"))
_lock = threading.RLock()
_conn = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  source TEXT NOT NULL,          -- agent | extension | observer | sim
  app TEXT NOT NULL,             -- mail | crm | chat | files | desktop | web
  action TEXT NOT NULL,
  target TEXT DEFAULT '',
  data TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS emails (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sender_name TEXT, sender_email TEXT, subject TEXT, body TEXT,
  attachment TEXT DEFAULT '', received_at TEXT, read INTEGER DEFAULT 0, handled_by INTEGER,
  source TEXT DEFAULT 'demo', file TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS customers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT, email TEXT, company TEXT, tier TEXT DEFAULT 'Standard',
  notes TEXT DEFAULT '[]', files TEXT DEFAULT '[]', updated_at TEXT
);
CREATE TABLE IF NOT EXISTS chat (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel TEXT, author TEXT, text TEXT, ts TEXT, bot INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS workflows (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT, intent TEXT, status TEXT,       -- suggested | active | paused | dismissed
  spec TEXT, pattern TEXT, learned TEXT DEFAULT '{}', stats TEXT DEFAULT '{}',
  signature TEXT UNIQUE, created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workflow_id INTEGER, status TEXT,          -- running | done | failed | needs_you
  trigger TEXT, vars TEXT DEFAULT '{}', steps TEXT DEFAULT '[]', note TEXT DEFAULT '',
  started_at TEXT, finished_at TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

DEFAULTS = {"observing": "1", "api_outage": "0", "user_name": "Yash", "groq_key": "", "jev_key": "",
            "session_gap_min": "4", "min_support": "2", "min_dwell_sec": "20",
            "ignore_apps": "whatsapp, telegram, discord, spotify, youtube, netflix, primevideo, hotstar, instagram, facebook, twitter, x.com, reddit"}


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def conn():
    global _conn
    with _lock:
        if _conn is None:
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.executescript(SCHEMA)
            for col in ("source TEXT DEFAULT 'demo'", "file TEXT DEFAULT ''"):  # databases from before Gmail support
                try:
                    _conn.execute(f"ALTER TABLE emails ADD COLUMN {col}")
                except sqlite3.OperationalError:
                    pass
            for k, v in DEFAULTS.items():
                _conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)", (k, v))
            _conn.commit()
        return _conn


def q(sql, args=()):
    with _lock:
        return [dict(r) for r in conn().execute(sql, args).fetchall()]


def one(sql, args=()):
    r = q(sql, args)
    return r[0] if r else None


def ex(sql, args=()):
    with _lock:
        cur = conn().execute(sql, args)
        conn().commit()
        return cur.lastrowid


def settings() -> dict:
    return {r["key"]: r["value"] for r in q("SELECT * FROM settings")}


def set_setting(k, v):
    ex("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))


def js(v, default=None):
    try:
        return json.loads(v) if isinstance(v, str) else (v if v is not None else default)
    except (TypeError, ValueError):
        return default


def reset():
    with _lock:
        c = conn()
        for t in ("events", "emails", "customers", "chat", "workflows", "runs"):
            c.execute(f"DELETE FROM {t}")
        c.execute("DELETE FROM sqlite_sequence")
        c.commit()
