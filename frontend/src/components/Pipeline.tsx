import { motion } from "framer-motion";
import { Check, CircleAlert, Hand, LoaderCircle, OctagonX, SkipForward, Split, X, Wand2 } from "lucide-react";
import clsx from "clsx";
import type { RunStep, Spec } from "../lib/types";
import AppGlyph from "./AppGlyph";
import { spring } from "./ui";

export const TIER = {
  api: { label: "API", full: "API integration" },
  app: { label: "App", full: "Application integration" },
  browser: { label: "Browser", full: "Browser automation (Playwright)" },
  vision: { label: "Vision", full: "Vision / UI fallback" },
  learned: { label: "Learned", full: "Remembered from last time" },
  you: { label: "You", full: "You answered" },
} as Record<string, { label: string; full: string }>;

/** Highlights {{variables}} inside a template. */
export function Template({ text }: { text: string }) {
  const parts = text.split(/(\{\{\s*\w+\s*\}\})/g);
  return (
    <span>
      {parts.map((p, i) => /^\{\{/.test(p)
        ? <span key={i} className="mx-0.5 rounded-md bg-flow/15 px-1 py-px font-medium text-flow">{p.replace(/[{}\s]/g, "").replace(/_/g, " ")}</span>
        : <span key={i}>{p}</span>)}
    </span>
  );
}

function StatusIcon({ s }: { s?: RunStep["status"] }) {
  if (s === "done") return <span className="grid h-5 w-5 place-items-center rounded-full bg-flow text-ink"><Check className="h-3 w-3" /></span>;
  if (s === "running") return <LoaderCircle className="h-5 w-5 animate-spin text-flow" />;
  if (s === "failed") return <span className="grid h-5 w-5 place-items-center rounded-full bg-bad text-ink"><X className="h-3 w-3" /></span>;
  if (s === "waiting") return <span className="grid h-5 w-5 place-items-center rounded-full bg-hand text-ink"><Hand className="h-3 w-3" /></span>;
  if (s === "skipped") return <span className="grid h-5 w-5 place-items-center rounded-full border border-white/25 text-faint"><SkipForward className="h-3 w-3" /></span>;
  return <span className="h-5 w-5 rounded-full border border-white/20" />;
}

/** The workflow as a flow of nodes. Pass `run` to animate a live execution. */
export default function Pipeline({ spec, run, compact, changed }: { spec: Spec; run?: RunStep[]; compact?: boolean; changed?: Set<string> }) {
  const runningIdx = run ? spec.steps.findIndex((st) => run.find((r) => r.id === st.id)?.status === "running") : -1;
  const cond = spec.conditions?.[0];
  return (
    <ol className="relative space-y-0" aria-label="Workflow steps">
      <Node first>
        <AppGlyph app="trigger" />
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-medium text-hand">When</p>
          <p className="font-medium leading-snug">{spec.trigger.label}</p>
        </div>
      </Node>
      {spec.steps.map((st, i) => {
        const rs = run?.find((r) => r.id === st.id);
        const isNew = changed?.has(st.id);
        const active = rs?.status === "running";
        const lineActive = run ? (rs?.status === "running" || (i <= runningIdx && runningIdx >= 0)) : false;
        return (
          <li key={st.id} className="relative">
            <div className="ml-[17px] h-4 w-0.5">
              <div className={clsx("h-full w-full", lineActive ? "flowline-v" : "flowline-v idle")} />
            </div>
            <motion.div layout transition={spring}
              data-changed={isNew ? "true" : undefined}
              className={clsx("relative flex items-start gap-3 rounded-2xl border p-3 transition-colors",
                active ? "border-flow/60 bg-flow/[0.07] shadow-[0_0_0_4px_rgba(52,214,196,0.08)]" :
                  rs?.status === "waiting" ? "border-hand/50 bg-hand/[0.06]" :
                    rs?.status === "failed" ? "border-bad/50 bg-bad/[0.06]" :
                      rs?.status === "skipped" ? "border-white/10 bg-transparent opacity-60" :
                        isNew ? "border-ok/50 bg-ok/[0.06] shadow-[0_0_0_4px_rgba(91,228,155,0.08)]" : "border-white/10 bg-white/[0.025]")}>
              {active && <motion.span className="absolute inset-0 rounded-2xl border border-flow/60" animate={{ opacity: [0.8, 0, 0.8] }} transition={{ duration: 1.4, repeat: Infinity }} />}
              <AppGlyph app={st.app} />
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-2">
                  <p className="font-medium leading-snug">{st.label}</p>
                  {run && <StatusIcon s={rs?.status} />}
                </div>
                {!compact && st.params && (st.params.note || st.params.text) && (
                  <p className="mt-1 text-[13px] leading-relaxed text-mist"><Template text={st.params.note || st.params.text || ""} /></p>
                )}
                {st.when && (
                  <p className="mt-1.5 inline-flex items-center gap-1.5 rounded-lg border border-dashed border-hand/45 px-2 py-0.5 text-[12px] text-hand">
                    <Split className="h-3.5 w-3.5" />{st.when.label}
                  </p>
                )}
                {!compact && st.learned_confidence != null && st.learned_confidence > 0 && (
                  <p className="mt-1 text-[11px] text-faint">Wording learned from your last runs · matched {Math.round(st.learned_confidence * 100)}% of them</p>
                )}
                {rs && (rs.tried.length > 0 || rs.detail) && (
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    {rs.tried.map((t, k) => (
                      <span key={k} title={t.detail}
                        className={clsx("inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium",
                          t.ok ? "bg-flow/15 text-flow" : "bg-bad/10 text-bad line-through decoration-bad/50")}>
                        {t.ok ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}{TIER[t.tier]?.label || t.tier}
                      </span>
                    ))}
                    {rs.tier === "you" && <span className="rounded-md bg-hand/15 px-1.5 py-0.5 text-[11px] font-medium text-hand">You</span>}
                    {rs.detail && <span className="text-xs text-mist">{rs.detail}</span>}
                    {rs.ms > 0 && <span className="text-[11px] text-faint">{(rs.ms / 1000).toFixed(1)}s</span>}
                    {rs.undone && <span className="rounded-md bg-white/10 px-1.5 py-0.5 text-[11px] font-medium text-mist">Undone</span>}
                  </div>
                )}
                {rs?.healed && rs.healed.length > 0 && (
                  <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
                    className="mt-2 rounded-xl border border-volt/35 bg-volt/[0.08] p-2.5">
                    <p className="flex items-center gap-1.5 text-[12px] font-semibold text-volt"><Wand2 className="h-3.5 w-3.5" />The app changed. I adapted.</p>
                    <ul className="mt-1 space-y-0.5 text-[12px] text-mist">
                      {rs.healed.map((h, k) => (
                        <li key={k}><span className="text-paper">{h.target}</span>: <span className="line-through decoration-bad/60">{h.before}</span> → <span className="text-paper">{h.after}</span></li>
                      ))}
                    </ul>
                  </motion.div>
                )}
                {!run && !compact && st.tiers && (
                  <p className="mt-1.5 text-[11px] text-faint">{st.tiers.join() === "you" ? "You do this step, then it carries on" : `Tries ${st.tiers.map((t) => TIER[t]?.label || t).join(" → ")}`}</p>
                )}
              </div>
            </motion.div>
            {cond && cond.after === st.id && (
              <div className="ml-9 mt-2 flex items-center gap-2 rounded-xl border border-dashed border-hand/40 px-3 py-2 text-[13px] text-hand">
                <Split className="h-4 w-4 shrink-0" />{cond.label}
              </div>
            )}
          </li>
        );
      })}
      <li className="ml-[17px] h-4 w-0.5"><div className={clsx("h-full w-full", run?.every((s) => s.status === "done") ? "flowline-v" : "flowline-v idle")} /></li>
      <li className="flex items-center gap-2 pl-1.5 text-sm text-faint">
        {run?.some((s) => s.status === "failed") ? <OctagonX className="h-5 w-5 text-bad" /> :
          run?.some((s) => s.status === "waiting") ? <CircleAlert className="h-5 w-5 text-hand" /> :
            <span className={clsx("h-5 w-5 rounded-full border-2", run?.every((s) => s.status === "done") ? "border-flow bg-flow/30" : "border-white/20")} />}
        {!run ? "Done" : run.every((s) => s.status === "done") ? "Finished" : run.some((s) => s.status === "waiting") ? "Paused until you answer" : run.some((s) => s.status === "failed") ? "Stopped" : "Running…"}
      </li>
    </ol>
  );
}

function Node({ children, first }: { children: React.ReactNode; first?: boolean }) {
  return <li className={clsx("flex items-center gap-3 rounded-2xl border border-hand/30 bg-hand/[0.05] p-3", first && "")}>{children}</li>;
}
