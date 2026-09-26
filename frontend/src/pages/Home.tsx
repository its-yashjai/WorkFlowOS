import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, CheckCircle2, CircleAlert, Clock3, Eye, Hand, LoaderCircle, MailPlus, Play, Sparkles, XCircle, Undo2, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import clsx from "clsx";
import ActivityFeed from "../components/ActivityFeed";
import AppGlyph, { APPS } from "../components/AppGlyph";
import { Logo } from "../components/Shell";
import { Button, Chip, CountUp, softSpring } from "../components/ui";
import { api } from "../lib/api";
import { dur, timeAgo } from "../lib/format";
import { useApp } from "../lib/store";
import type { Run, Workflow } from "../lib/types";

function AppChain({ apps }: { apps: string[] }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {apps.map((a, i) => (
        <span key={a + i} className="flex items-center gap-1.5">
          {i > 0 && <ArrowRight className="h-3.5 w-3.5 text-faint" />}
          <span className="flex items-center gap-1.5 rounded-lg bg-white/[0.05] py-1 pl-1 pr-2 text-xs"><AppGlyph app={a} size="sm" />{APPS[a]?.label || a}</span>
        </span>
      ))}
    </div>
  );
}

function Suggested({ w, i }: { w: Workflow; i: number }) {
  const ev = w.spec.evidence;
  return (
    <motion.div layout initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ ...softSpring, delay: i * 0.06 }}
      className="relative overflow-hidden rounded-3xl border border-hand/35 bg-gradient-to-br from-hand/[0.10] to-transparent p-5">
      <p className="flex items-center gap-2 text-sm font-medium text-hand"><Sparkles className="h-4 w-4" />Found in your work</p>
      <h3 className="mt-1 font-display text-2xl font-bold tracking-tight">{w.name}</h3>
      <p className="mt-1 text-sm text-mist">{w.intent}</p>
      <div className="mt-4 grid grid-cols-3 gap-2">
        <Stat big={`${ev.times_seen}×`} small="times you did it" />
        <Stat big={dur(ev.avg_manual_seconds)} small="each time, by hand" />
        <Stat big={String(ev.app_switches)} small="app switches" />
      </div>
      <div className="mt-4"><AppChain apps={ev.apps} /></div>
      <Link to={`/workflow/${w.id}`} className="mt-5 block">
        <Button variant="primary" className="w-full sm:w-auto" icon={<ArrowRight className="h-4 w-4" />}>Review and automate</Button>
      </Link>
    </motion.div>
  );
}

function Stat({ big, small }: { big: string; small: string }) {
  return (
    <div className="rounded-2xl bg-ink/50 p-3">
      <p className="font-display text-2xl font-bold">{big}</p>
      <p className="text-[11.5px] leading-tight text-mist">{small}</p>
    </div>
  );
}

const RUN_ICON = {
  done: <CheckCircle2 className="h-4 w-4 text-ok" />, failed: <XCircle className="h-4 w-4 text-bad" />,
  needs_you: <Hand className="h-4 w-4 text-hand" />, running: <LoaderCircle className="h-4 w-4 animate-spin text-flow" />,
  undone: <Undo2 className="h-4 w-4 text-mist" />, cancelled: <XCircle className="h-4 w-4 text-faint" />,
};

export default function Home() {
  const { state, version, lastRun, toast } = useApp();
  const nav = useNavigate();
  const [wfs, setWfs] = useState<Workflow[] | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [sending, setSending] = useState(false);
  useEffect(() => { api.workflows().then(setWfs); }, [version.workflows, version.runs]);
  useEffect(() => { api.runs(8).then(setRuns); }, [version.runs]);
  const suggested = (wfs || []).filter((w) => w.status === "suggested");
  const active = (wfs || []).filter((w) => w.status === "active" || w.status === "paused");
  const c = state?.counts;
  const live = runs.find((r) => r.id === lastRun && r.status === "running");
  const name = state?.settings.user_name || "there";

  return (
    <div className="mx-auto max-w-6xl px-4 pb-12 pt-5 sm:px-6 lg:pt-10">
      <div className="mb-6 lg:hidden"><Logo /></div>
      <header className="mb-7 max-w-3xl">
        <p className="flex flex-wrap items-center gap-2 text-sm text-mist">Hi {name}. I've been watching how you work.
          {state?.connectors?.gmail.connected && <span className="rounded-md bg-[#E8544E]/15 px-1.5 py-0.5 text-[11px] text-[#FF8A84]">Gmail connected</span>}
          {state?.connectors?.slack.connected && <span className="rounded-md bg-volt/15 px-1.5 py-0.5 text-[11px] text-volt">Slack connected</span>}
          {state?.ai?.engine === "ollama" && <span className="inline-flex items-center gap-1 rounded-md bg-ok/15 px-1.5 py-0.5 text-[11px] text-ok"><ShieldCheck className="h-3 w-3" />On-device AI · nothing leaves this computer</span>}
        </p>
        <motion.h1 initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={softSpring}
          className="mt-1 font-display text-[34px] font-bold leading-[1.05] tracking-tight sm:text-5xl">
          {wfs == null ? "Looking for patterns…" : suggested.length
            ? <>You keep repeating {suggested.length === 1 ? "one routine" : `${suggested.length} routines`}. <span className="text-hand">I can do {suggested.length === 1 ? "it" : "them"} for you.</span></>
            : active.length ? <>{active.length} routine{active.length > 1 ? "s" : ""} now run{active.length > 1 ? "" : "s"} <span className="text-flow">on autopilot.</span></> : "Nothing repeated yet. Keep working as usual."}
        </motion.h1>
      </header>

      <div className="mb-7 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        {[{ l: "actions observed", v: c?.events ?? 0 }, { l: "routines found", v: (c?.suggested ?? 0) + (c?.active ?? 0) },
          { l: "automatic runs", v: c?.runs ?? 0 }].map((x) => (
          <div key={x.l} className="panel rounded-2xl p-4"><p className="font-display text-3xl font-bold"><CountUp value={x.v} /></p><p className="text-sm text-mist">{x.l}</p></div>
        ))}
        <div className="panel rounded-2xl p-4"><p className="font-display text-3xl font-bold text-flow">{dur(c?.time_saved_sec)}</p><p className="text-sm text-mist">of your time saved</p></div>
      </div>

      <AnimatePresence>
        {live && (
          <motion.button initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} onClick={() => nav(`/run/${live.id}`)}
            className="mb-6 flex w-full items-center gap-3 rounded-2xl border border-flow/40 bg-flow/[0.08] p-4 text-left">
            <LoaderCircle className="h-5 w-5 animate-spin text-flow" />
            <span className="flex-1"><b>{live.workflow_name}</b> is running on "{live.trigger.subject}"</span>
            <span className="text-sm text-flow">Watch it live →</span>
          </motion.button>
        )}
      </AnimatePresence>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-6">
          {suggested.map((w, i) => <Suggested key={w.id} w={w} i={i} />)}

          <section>
            <div className="mb-2 flex items-center justify-between gap-3">
              <h2 className="font-display text-lg font-semibold">On autopilot</h2>
              {active.some((w) => w.status === "active") && (
                <Button size="sm" busy={sending} icon={<MailPlus className="h-4 w-4" />} onClick={async () => {
                  setSending(true);
                  try { const r = await api.testEmail(); if (r.runs.length) { toast("New email arrived. Workflow started", "good"); nav(`/run/${r.runs[0]}`); } else toast("Email arrived, but no active workflow matched it"); }
                  finally { setSending(false); }
                }}>Send a test email</Button>
              )}
            </div>
            {active.length === 0 ? (
              <p className="rounded-2xl border border-dashed border-white/15 p-5 text-sm text-mist">Nothing automated yet. Approve a routine above and it will run by itself next time.</p>
            ) : (
              <ul className="space-y-2">
                {active.map((w) => (
                  <li key={w.id}>
                    <Link to={`/workflow/${w.id}`} className="panel flex items-center gap-3 rounded-2xl p-4 hover:bg-white/[0.06]">
                      <span className={clsx("grid h-10 w-10 place-items-center rounded-xl", w.status === "active" ? "bg-flow/15 text-flow" : "bg-white/10 text-faint")}><Play className="h-4 w-4" /></span>
                      <div className="min-w-0 flex-1">
                        <p className="font-medium">{w.name}</p>
                        <p className="text-xs text-mist">{w.spec.trigger.label} · {w.stats.runs ?? 0} runs · saved {dur(w.stats.time_saved_sec)}</p>
                      </div>
                      <Chip tone={w.status === "active" ? "flow" : "mist"}>{w.status === "active" ? "Active" : "Paused"}</Chip>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <h2 className="mb-2 font-display text-lg font-semibold">Recent runs</h2>
            {runs.length === 0 ? <p className="text-sm text-mist">No runs yet.</p> : (
              <ul className="panel divide-y divide-white/[0.06] rounded-2xl">
                {runs.map((r) => (
                  <li key={r.id}>
                    <Link to={`/run/${r.id}`} className="flex items-center gap-3 px-4 py-3 hover:bg-white/[0.04]">
                      {RUN_ICON[r.status]}
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm"><b className="font-medium">{r.trigger.from}</b> · {r.trigger.subject}</p>
                        <p className="text-xs text-faint">{r.workflow_name} · {timeAgo(r.started_at)}</p>
                      </div>
                      {r.status === "needs_you" && <Chip tone="hand"><CircleAlert className="h-3 w-3" />Needs you</Chip>}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <aside className="panel h-fit min-w-0 rounded-3xl p-4 lg:sticky lg:top-6">
          <div className="mb-2 flex items-center justify-between px-1">
            <h2 className="flex items-center gap-2 font-display text-lg font-semibold"><Eye className="h-4 w-4 text-hand" />Watching now</h2>
            <Link to="/activity" className="text-xs text-mist hover:text-paper">Full timeline →</Link>
          </div>
          <p className="mb-2 px-1 text-xs text-faint">Every click in your apps becomes a structured event. Try the routine yourself in Mailbox, Ledger and Huddle.</p>
          <ActivityFeed limit={14} />
          <p className="mt-3 flex items-center gap-1.5 px-1 text-[11px] text-faint"><Clock3 className="h-3 w-3" />Discovery re-runs 2 seconds after you stop working.</p>
        </aside>
      </div>
    </div>
  );
}
