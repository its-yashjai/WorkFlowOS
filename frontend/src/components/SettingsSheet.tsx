import { Cpu, Download, Eye, EyeOff, KeyRound, MonitorDot, RotateCcw, ServerCrash, ShieldCheck, Unplug, MonitorPlay, Wand2 } from "lucide-react";
import { useEffect, useState } from "react";
import clsx from "clsx";
import { api } from "../lib/api";
import { timeAgo } from "../lib/format";
import { useApp } from "../lib/store";
import { Button, Sheet, Toggle } from "./ui";
import RealApps from "./RealApps";

export default function SettingsSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { state, refresh, toast } = useApp();
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [ignore, setIgnore] = useState("");
  const [dwell, setDwell] = useState("20");
  useEffect(() => {
    if (open && state) { setIgnore(state.settings.ignore_apps ?? ""); setDwell(state.settings.min_dwell_sec ?? "20"); }
  }, [open]);  // load once per opening, so typing isn't overwritten by live updates
  if (!state) return null;
  const s = state.settings;
  const noiseChanged = ignore.trim() !== (s.ignore_apps ?? "").trim() || dwell !== (s.min_dwell_sec ?? "20");
  const save = async (p: Record<string, unknown>) => { await api.settings(p); await refresh(); };
  return (
    <Sheet open={open} onClose={onClose} title="Settings">
      <div className="space-y-6">
        <section className="flex items-center justify-between gap-4">
          <div>
            <h3 className="flex items-center gap-2 font-display text-base font-semibold"><Eye className="h-4 w-4 text-hand" />Observe my work</h3>
            <p className="text-sm text-mist">Record app switches, browser pages and actions so repeated work can be found. Pause anytime.</p>
          </div>
          <Toggle label="Observe my work" on={s.observing === "1"} onChange={(v) => save({ observing: v })} />
        </section>

        <section className="space-y-2 rounded-2xl border hairline bg-white/[0.03] p-4">
          <h3 className="flex items-center gap-2 font-display text-base font-semibold"><MonitorDot className="h-4 w-4 text-flow" />Observers</h3>
          <ul className="space-y-1.5 text-sm">
            <li className="flex items-center justify-between"><span>App observer (Mailbox, Ledger, Huddle)</span><span className="text-ok">Built in</span></li>
            {state.agents.length === 0 && <li className="text-mist">No desktop agent or browser extension connected yet.</li>}
            {state.agents.map((a) => (
              <li key={a.name} className="flex items-center justify-between gap-2">
                <span className="truncate">{a.source === "extension" ? "Browser extension" : "Desktop agent"} · {a.name}</span>
                <span className={clsx("flex items-center gap-1.5", a.online ? "text-ok" : "text-faint")}>
                  <span className={clsx("h-2 w-2 rounded-full", a.online ? "bg-ok" : "bg-faint")} />{a.online ? "Live" : `seen ${timeAgo(a.last_seen)}`}
                </span>
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-2 pt-1">
            <a href="/downloads/wfos_agent.py" download><Button size="sm" icon={<Download className="h-3.5 w-3.5" />}>Desktop agent</Button></a>
            <a href="/downloads/wfos_extension.zip" download><Button size="sm" icon={<Download className="h-3.5 w-3.5" />}>Browser extension</Button></a>
          </div>
          <p className="text-xs text-faint">Agent: <code>python wfos_agent.py</code>. Extension: unzip, then Chrome → Extensions → Developer mode → Load unpacked.</p>
        </section>

        <section className="space-y-3 rounded-2xl border hairline bg-white/[0.03] p-4">
          <h3 className="flex items-center gap-2 font-display text-base font-semibold"><EyeOff className="h-4 w-4 text-hand" />What doesn't count as work</h3>
          <p className="text-sm text-mist">Quick switches to another app or tab are ignored, so they never end up as steps in a workflow.</p>
          <label className="block text-sm">Never part of a workflow
            <textarea rows={2} value={ignore} onChange={(e) => setIgnore(e.target.value)} placeholder="whatsapp, youtube, spotify"
              className="mt-1 w-full resize-none rounded-xl border border-white/12 bg-white/[0.04] px-3 py-2 text-sm outline-none placeholder:text-faint focus:border-volt" />
            <span className="mt-1 block text-xs text-faint">App names or websites, separated by commas. These are skipped however long you stay.</span>
          </label>
          <label className="flex items-center justify-between gap-4 text-sm">
            <span>Ignore a switch shorter than
              <span className="block text-xs text-faint">Unless you clicked, submitted or downloaded something there.</span>
            </span>
            <span className="flex shrink-0 items-center gap-2">
              <input type="number" min={0} max={600} value={dwell} onChange={(e) => setDwell(e.target.value)} aria-label="Seconds"
                className="h-10 w-20 rounded-xl border border-white/12 bg-white/[0.04] px-3 text-sm outline-none focus:border-volt" />
              <span className="text-mist">seconds</span>
            </span>
          </label>
          <Button size="sm" variant="primary" disabled={!noiseChanged} onClick={async () => {
            await save({ ignore_apps: ignore, min_dwell_sec: Math.max(0, Math.min(600, parseInt(dwell || "0", 10) || 0)) });
            toast("Saved. I looked at your activity again with the new rules", "good");
          }}>Save</Button>
        </section>

        <RealApps />

        <section className="space-y-3 rounded-2xl border border-dashed border-white/15 p-4">
          <h3 className="font-display text-base font-semibold">Demo: break things on purpose</h3>
          <div className="flex items-center justify-between gap-4">
            <p className="flex items-center gap-2 text-sm"><ServerCrash className="h-4 w-4 text-bad" />API is down</p>
            <Toggle label="Simulate API outage" on={s.api_outage === "1"} onChange={(v) => save({ api_outage: v })} />
          </div>
          <div className="flex items-center justify-between gap-4">
            <p className="flex items-center gap-2 text-sm"><Unplug className="h-4 w-4 text-bad" />App integration is down too</p>
            <Toggle label="Simulate app integration outage" on={s.app_outage === "1"} onChange={(v) => save({ app_outage: v })} />
          </div>
          <div className="flex items-center justify-between gap-4">
            <p className="flex items-center gap-2 text-sm"><MonitorPlay className="h-4 w-4 text-volt" />Show the browser while it automates</p>
            <Toggle label="Show automation browser" on={s.show_browser === "1"} onChange={(v) => save({ show_browser: v })} />
          </div>
          <div className="flex items-center justify-between gap-4">
            <p className="flex items-center gap-2 text-sm"><Wand2 className="h-4 w-4 text-volt" />Ledger CRM ships a redesign</p>
            <Toggle label="Ledger redesign" on={s.ui_v2 === "1"} onChange={(v) => save({ ui_v2: v })} />
          </div>
          <p className="text-xs text-faint">Runs fall back API → App integration → Browser automation, and you can watch each attempt. With the redesign on, buttons and fields get new names. Browser automation finds them by meaning and heals itself.</p>
        </section>

        <section className="space-y-3">
          <h3 className="flex items-center gap-2 font-display text-base font-semibold"><Cpu className="h-4 w-4 text-volt" />AI model</h3>
          <div className={clsx("flex items-start gap-3 rounded-2xl border p-3 text-sm", state.ai?.engine === "ollama" ? "border-ok/35 bg-ok/[0.06]" : "border-white/12 bg-white/[0.03]")}>
            <ShieldCheck className={clsx("mt-0.5 h-4 w-4 shrink-0", state.ai?.local ? "text-ok" : "text-hand")} />
            <div>
              <p className="font-medium">{state.ai?.label ?? "Checking…"}</p>
              <p className="text-xs text-mist">{state.ai?.engine === "ollama" ? "Runs on this computer through Ollama. Your activity never leaves this machine."
                : state.ai?.engine === "groq" ? "Uses Groq in the cloud. Turn on Local AI only to keep everything on this machine."
                : "Start Ollama with a model (e.g. ollama pull qwen2.5:3b) for on-device AI. Until then, built-in rules handle everything."}</p>
            </div>
          </div>
          <div className="flex items-center justify-between gap-4">
            <p className="text-sm">Local AI only (never send anything to the cloud)</p>
            <Toggle label="Local AI only" on={s.ai_local_only !== "0"} onChange={(v) => save({ ai_local_only: v })} />
          </div>
          <p className="flex items-center gap-2 pt-1 text-sm font-medium"><KeyRound className="h-4 w-4 text-volt" />Groq key (optional, cloud)</p>
          <p className="text-sm text-mist">Only used when Local AI only is off and no local model is running.</p>
          <form className="flex gap-2" onSubmit={async (e) => { e.preventDefault(); if (!key.trim()) return; await save({ groq_key: key.trim() }); setKey(""); toast("Groq key saved", "good"); }}>
            <input type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder={state.groq_key_set ? "Saved. Paste to replace" : "Not needed. Paste a key from console.groq.com only if you want a cloud backup"}
              className="h-10 min-w-0 flex-1 rounded-xl border border-white/12 bg-white/[0.04] px-3 text-sm outline-none placeholder:text-faint focus:border-volt" />
            <Button size="sm" className="h-10" disabled={!key.trim()}>Save</Button>
          </form>
        </section>

        <Button variant="danger" size="sm" busy={busy} icon={<RotateCcw className="h-4 w-4" />} onClick={async () => {
          if (!confirm("Reset to the demo data (a simulated week of work)?")) return;
          setBusy(true);
          try { await api.reset(); await refresh(); toast("Demo data restored", "good"); onClose(); } finally { setBusy(false); }
        }}>Reset demo data</Button>
      </div>
    </Sheet>
  );
}
