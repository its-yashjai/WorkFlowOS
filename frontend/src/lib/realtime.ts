import { useEffect, useRef, useState } from "react";

export type RtEvent = { type: string; [k: string]: unknown };

type Listener = (e: RtEvent) => void;

/** One shared socket per path, auto-reconnecting, fan-out to subscribers. */
class Socket {
  ws: WebSocket | null = null;
  listeners = new Set<Listener>();
  status: "connecting" | "open" | "closed" = "connecting";
  statusListeners = new Set<(s: string) => void>();
  retry = 0;
  constructor(public path: string) { this.connect(); }
  connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}${this.path}`);
    this.ws = ws;
    this.setStatus("connecting");
    ws.onopen = () => { this.retry = 0; this.setStatus("open"); };
    ws.onmessage = (m) => {
      try { const e = JSON.parse(m.data); this.listeners.forEach((l) => l(e)); } catch { /* ignore */ }
    };
    ws.onclose = () => {
      this.setStatus("closed");
      const wait = Math.min(8000, 500 * 2 ** this.retry++);
      setTimeout(() => this.connect(), wait);
    };
  }
  setStatus(s: "connecting" | "open" | "closed") { this.status = s; this.statusListeners.forEach((l) => l(s)); }
  send(obj: unknown) { if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(obj)); }
}

const sockets = new Map<string, Socket>();
export function socket(path: string) {
  if (!sockets.has(path)) sockets.set(path, new Socket(path));
  return sockets.get(path)!;
}

export function useRealtime(path: string, fn: Listener) {
  const ref = useRef(fn);
  ref.current = fn;
  const [status, setStatus] = useState(() => socket(path).status);
  useEffect(() => {
    const s = socket(path);
    const l: Listener = (e) => ref.current(e);
    const sl = (st: string) => setStatus(st as typeof status);
    s.listeners.add(l);
    s.statusListeners.add(sl);
    return () => { s.listeners.delete(l); s.statusListeners.delete(sl); };
  }, [path]);
  return { status, send: (o: unknown) => socket(path).send(o) };
}
