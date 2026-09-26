"""WorkFlowOS Desktop Activity Agent.

Watches what you do on your computer and sends structured events to WorkFlowOS:
  * which app / window is in front   -> desktop.app_focus  {process, title}
  * files that land in your Downloads -> files.file_saved   {filename, folder, ext}
  * files you create/rename in extra watched folders (--watch)

Privacy by design:
  * no keystrokes, no screenshots, no clipboard
  * window titles containing sensitive words are masked
  * --no-titles sends only the app name
  * pauses automatically when WorkFlowOS observing is switched off

Standard library only. Windows is fully supported; macOS and Linux (X11 with xdotool) work for app focus.

Usage:
    python wfos_agent.py                       # server http://localhost:8765
    python wfos_agent.py --server http://192.168.1.5:8765 --watch "C:\\Users\\me\\Documents\\Invoices"
"""
import argparse
import json
import os
import platform
import queue
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime

SENSITIVE = ("password", "passwort", "bank", "login", "sign in", "otp", "2fa", "private", "incognito", "inprivate",
             "credit card", "payroll", "medical")
IGNORE_EXT = (".crdownload", ".part", ".tmp", ".download", ".partial")
IGNORE_PROC = {"searchhost.exe", "shellexperiencehost.exe", "startmenuexperiencehost.exe", "lockapp.exe",
               "applicationframehost.exe", "textinputhost.exe", "python.exe", "pythonw.exe", "windowsterminal.exe"}

OS = platform.system()


def now():
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- foreground window
if OS == "Windows":
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    def foreground():
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None, None
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc = ""
        h = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if h:
            size = wintypes.DWORD(1024)
            pbuf = ctypes.create_unicode_buffer(1024)
            if kernel32.QueryFullProcessImageNameW(h, 0, pbuf, ctypes.byref(size)):
                proc = os.path.basename(pbuf.value)
            kernel32.CloseHandle(h)
        return proc, buf.value

    def idle_seconds():
        li = LASTINPUTINFO()
        li.cbSize = ctypes.sizeof(li)
        if not user32.GetLastInputInfo(ctypes.byref(li)):
            return 0
        return (kernel32.GetTickCount() - li.dwTime) / 1000.0

elif OS == "Darwin":
    def foreground():
        script = ('tell application "System Events" to set p to first application process whose frontmost is true\n'
                  'set n to name of p\ntry\nset t to name of front window of p\non error\nset t to ""\nend try\n'
                  'return n & "|" & t')
        try:
            out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=3).stdout.strip()
            proc, _, title = out.partition("|")
            return proc, title
        except Exception:
            return None, None

    def idle_seconds():
        return 0

else:
    def foreground():
        try:
            wid = subprocess.run(["xdotool", "getactivewindow"], capture_output=True, text=True, timeout=2).stdout.strip()
            title = subprocess.run(["xdotool", "getwindowname", wid], capture_output=True, text=True, timeout=2).stdout.strip()
            pid = subprocess.run(["xdotool", "getwindowpid", wid], capture_output=True, text=True, timeout=2).stdout.strip()
            proc = open(f"/proc/{pid}/comm").read().strip() if pid else ""
            return proc, title
        except Exception:
            return None, None

    def idle_seconds():
        return 0


def clean_title(title, proc, no_titles):
    if no_titles or not title:
        return ""
    low = title.lower()
    if any(w in low for w in SENSITIVE):
        return "(hidden for privacy)"
    return title[:140]


# ---------------------------------------------------------------- agent
class Agent:
    def __init__(self, server, watch, no_titles, interval):
        self.server = server.rstrip("/")
        self.watch = watch
        self.no_titles = no_titles
        self.interval = interval
        self.q = queue.Queue()
        self.observing = True
        self.name = f"desktop-agent@{socket.gethostname()}"
        self.sent = 0

    def post(self, path, body):
        req = urllib.request.Request(self.server + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.load(r)

    def emit(self, app, action, target, data):
        if self.observing:
            self.q.put({"app": app, "action": action, "target": target, "data": data, "source": "agent", "ts": now()})

    # --- loops
    def heartbeat_loop(self):
        while True:
            try:
                r = self.post("/api/agents/heartbeat", {"name": self.name, "source": "agent",
                                                         "info": {"os": f"{OS} {platform.release()}", "sent": self.sent,
                                                                  "watching": self.watch}})
                if r.get("observing") != self.observing:
                    self.observing = bool(r.get("observing"))
                    print("[wfos] observing", "ON" if self.observing else "PAUSED from WorkFlowOS settings")
            except Exception as e:
                print("[wfos] server not reachable:", e)
            time.sleep(10)

    def sender_loop(self):
        while True:
            batch = [self.q.get()]
            time.sleep(1.5)
            while not self.q.empty():
                batch.append(self.q.get_nowait())
            try:
                r = self.post("/api/events", batch)
                self.sent += r.get("stored", 0)
            except Exception as e:
                print("[wfos] could not send", len(batch), "events:", e)

    def focus_loop(self):
        reported = (None, None)        # last window we sent
        candidate, since = (None, None), time.time()
        while True:
            time.sleep(min(self.interval, 0.5))
            if idle_seconds() > 120:
                continue
            proc, title = foreground()
            if not proc or proc.lower() in IGNORE_PROC:
                continue
            cur = (proc, clean_title(title, proc, self.no_titles))
            if cur != candidate:       # a new window came to the front: start its timer
                candidate, since = cur, time.time()
                continue
            # report a window once you've stayed on it for 1.5 s (quick alt-tab flicker is ignored)
            if cur != reported and time.time() - since >= 1.5:
                reported = cur
                self.emit("desktop", "app_focus", proc, {"process": proc, "title": cur[1]})
                print(f"[wfos] focus  {proc}  {cur[1][:60]}")

    def folder_loop(self):
        seen = {d: self._snapshot(d) for d in self.watch}
        while True:
            time.sleep(2)
            for d in self.watch:
                cur = self._snapshot(d)
                for f in cur - seen[d]:
                    if f.lower().endswith(IGNORE_EXT) or f.startswith("~$") or f.startswith("."):
                        continue
                    ext = os.path.splitext(f)[1].lower().lstrip(".")
                    self.emit("files", "file_saved", f, {"filename": f, "folder": os.path.basename(d) or d, "ext": ext})
                    print(f"[wfos] file   {f}  in {d}")
                seen[d] = cur

    @staticmethod
    def _snapshot(d):
        try:
            return set(os.listdir(d))
        except OSError:
            return set()

    def run(self):
        print(f"[wfos] WorkFlowOS agent -> {self.server}")
        print(f"[wfos] watching app focus and folders: {', '.join(self.watch) or '(none)'}")
        print("[wfos] no keystrokes, screenshots or clipboard are ever recorded. Ctrl+C to stop.")
        for fn in (self.heartbeat_loop, self.sender_loop, self.focus_loop, self.folder_loop):
            threading.Thread(target=fn, daemon=True).start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[wfos] stopped")


def main():
    for stream in (sys.stdout, sys.stderr):  # Windows consoles can't print every window title
        try:
            stream.reconfigure(errors="replace")
        except Exception:  # noqa: BLE001
            pass
    ap = argparse.ArgumentParser(description="WorkFlowOS desktop activity agent")
    ap.add_argument("--server", default=os.environ.get("WFOS_SERVER", "http://localhost:8765"))
    ap.add_argument("--watch", action="append", default=[], help="extra folder to watch (repeatable)")
    ap.add_argument("--no-downloads", action="store_true", help="don't watch the Downloads folder")
    ap.add_argument("--no-titles", action="store_true", help="send only app names, never window titles")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between focus checks")
    a = ap.parse_args()
    watch = list(a.watch)
    dl = os.path.join(os.path.expanduser("~"), "Downloads")
    if not a.no_downloads and os.path.isdir(dl):
        watch.insert(0, dl)
    Agent(a.server, watch, a.no_titles, a.interval).run()


if __name__ == "__main__":
    sys.exit(main())
