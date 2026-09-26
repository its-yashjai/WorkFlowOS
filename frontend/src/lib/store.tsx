import { AnimatePresence, motion } from "framer-motion";
import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { useRealtime } from "./realtime";
import type { AppState } from "./types";

interface Toast { id: number; text: string; tone?: "good" | "bad" | "info" }
interface Ctx {
  state: AppState | null; refresh: () => Promise<void>; toast: (t: string, tone?: Toast["tone"]) => void;
  version: { activity: number; workflows: number; runs: number; apps: number }; lastRun: number | null;
}
const C = createContext<Ctx>(null as unknown as Ctx);
export const useApp = () => useContext(C);

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AppState | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [version, setVersion] = useState({ activity: 0, workflows: 0, runs: 0, apps: 0 });
  const [lastRun, setLastRun] = useState<number | null>(null);
  const refresh = useCallback(async () => { try { setState(await api.state()); } catch { /* offline */ } }, []);
  useEffect(() => { refresh(); const t = setInterval(refresh, 15000); return () => clearInterval(t); }, [refresh]);
  const bump = (k: keyof Ctx["version"]) => setVersion((v) => ({ ...v, [k]: v[k] + 1 }));
  useRealtime("/ws", (e) => {
    const ev = e as unknown as { type: string; run_id?: number; started?: boolean };
    if (ev.type === "activity") { bump("activity"); refresh(); }
    if (ev.type === "workflows") { bump("workflows"); refresh(); }
    if (ev.type === "run") { bump("runs"); if (ev.started && ev.run_id) setLastRun(ev.run_id); refresh(); }
    if (ev.type === "apps") bump("apps");
    if (ev.type === "state") refresh();
  });
  const toast = useCallback((text: string, tone: Toast["tone"] = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3400);
  }, []);
  const value = useMemo(() => ({ state, refresh, toast, version, lastRun }), [state, refresh, toast, version, lastRun]);
  return (
    <C.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-24 z-[70] flex flex-col items-center gap-2 px-4 lg:bottom-6" aria-live="polite">
        <AnimatePresence>
          {toasts.map((t) => (
            <motion.div key={t.id} initial={{ opacity: 0, y: 14, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -8 }}
              className={`panel pointer-events-auto rounded-full px-4 py-2 text-sm shadow-xl ${t.tone === "good" ? "text-ok" : t.tone === "bad" ? "text-bad" : "text-paper"}`}>
              {t.text}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </C.Provider>
  );
}
