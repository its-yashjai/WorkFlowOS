import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, Brain, CheckCircle2, Hand, LoaderCircle, Pause, Pencil, Play, ShieldCheck, Sparkles, X, XCircle, Eye, Rocket, Undo2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import AppGlyph from "../components/AppGlyph";
import Pipeline, { Template, TIER } from "../components/Pipeline";
import { Button, Chip, Segmented, softSpring, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { dayTime, dur, timeAgo, when } from "../lib/format";
import { useApp } from "../lib/store";
import type { AskResult, Run, Spec, Workflow } from "../lib/types";
import AskChange from "../components/AskChange";

const STATUS = {
  suggested: { tone: "hand" as const, label: "Waiting for your approval" },
  active: { tone: "flow" as const, label: "Active" },
  paused: { tone: "mist" as const, label: "Paused" },
  dismissed: { tone: "mist" as const, label: "Dismissed" },
};

function Editor({ spec, onSave, onCancel }: { spec: Spec; onSave: (s: Spec) => void; onCancel: () => void }) {
  const [draft, setDraft] = useState<Spec>(JSON.parse(JSON.stringify(spec)));
  const vars = ["customer_name", "customer_email", "company", "subject", "attachment"];
  const set = (i: number, k: string, v: string) => setDraft((d) => {
    const n = { ...d, steps: d.steps.map((s) => ({ ...s, params: { ...(s.params || {}) } })) };
    n.steps[i].params![k] = v;
    return n;
  });
  return (
    <div className="space-y-4">
      {draft.steps.map((s, i) => (s.params?.note != null || s.params?.text != null) && (
        <div key={s.id} className="rounded-2xl border hairline p-3">
          <p className="mb-2 flex items-center gap-2 text-sm font-medium"><AppGlyph app={s.app} size="sm" />{s.label}</p>
          {s.params?.channel != null && (
            <label className="mb-2 block text-xs text-mist">Channel
              <input value={s.params.channel} onChange={(e) => set(i, "channel", e.target.value)} className="mt-1 h-9 w-full rounded-lg border border-white/12 bg-ink/60 px-2 text-sm text-paper outline-none focus:border-volt" />
            </label>
          )}
          <label className="block text-xs text-mist">{s.params?.note != null ? "Note to add" : "Message to send"}
            <textarea rows={2} value={s.params?.note ?? s.params?.text ?? ""} onChange={(e) => set(i, s.params?.note != null ? "note" : "text", e.target.value)}
              className="mt-1 w-full resize-none rounded-lg border border-white/12 bg-ink/60 px-2 py-1.5 text-sm text-paper outline-none focus:border-volt" />
          </label>
          <p className="mt-1.5 text-[11px] text-faint">Insert: {vars.map((v) => (
            <button key={v} type="button" className="mr-1 rounded bg-flow/10 px-1 text-flow hover:bg-flow/20"
              onClick={() => set(i, s.params?.note != null ? "note" : "text", (s.params?.note ?? s.params?.text ?? "") + ` {{${v}}}`)}>{v.replace("_", " ")}</button>
          ))}</p>
        </div>
      ))}
      <div className="flex gap-2">
        <Button variant="primary" onClick={() => onSave(draft)}>Save changes</Button>
        <Button variant="quiet" onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  );
}

function Autonomy({ w, onChange }: { w: Workflow; onChange: (w: Workflow) => void }) {
  const { toast } = useApp();
  const mode = w.learned.mode || "auto";
  const streak = w.stats.clean_streak || 0;
  const set = async (m: "preview" | "auto") => {
    onChange(await api.patchWorkflow(w.id, { mode: m }));
    toast(m === "auto" ? "On autopilot. It runs without asking, and you can still undo any run" : "It will show you changes before making them", "good");
  };
  return (
    <section className="space-y-3">
      <AnimatePresence>
        {w.learned.suggest_auto && mode === "preview" && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={softSpring}
            className="rounded-3xl border border-flow/40 bg-flow/[0.08] p-5">
            <p className="flex items-center gap-2 font-display text-lg font-semibold text-flow"><Rocket className="h-5 w-5" />It's earned your trust</p>
            <p className="mt-1 text-sm">{streak} runs in a row where you approved the preview without changing anything. Let it run by itself? You can still undo any run.</p>
            <Button className="mt-3" variant="good" icon={<Rocket className="h-4 w-4" />} onClick={() => set("auto")}>Switch to autopilot</Button>
          </motion.div>
        )}
      </AnimatePresence>
      <div className="panel flex flex-wrap items-center justify-between gap-3 rounded-2xl p-4">
        <div className="min-w-0">
          <p className="text-sm font-medium">How much it does alone</p>
          <p className="text-xs text-mist">{mode === "preview"
            ? `Shows you every change first · ${streak}/2 clean runs toward autopilot`
            : "Runs by itself. Undo is always one click away."}</p>
        </div>
        <Segmented layoutId={`mode-${w.id}`} size="sm" value={mode} onChange={set}
          options={[{ value: "preview", label: "Preview first", icon: <Eye className="h-3.5 w-3.5" /> }, { value: "auto", label: "Autopilot", icon: <Rocket className="h-3.5 w-3.5" /> }]} />
      </div>
    </section>
  );
}

export default function WorkflowPage() {
  const id = Number(useParams().id);
  const nav = useNavigate();
  const { version, toast, refresh } = useApp();
  const [w, setW] = useState<Workflow | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [editing, setEditing] = useState(false);
  const [proposal, setProposal] = useState<AskResult | null>(null);
  const [justChanged, setJustChanged] = useState<Set<string> | undefined>(undefined);
  const [busy, setBusy] = useState<string | null>(null);
  const load = () => api.workflow(id).then((r) => { setW(r.workflow); setRuns(r.runs); });
  useEffect(() => { load(); }, [id, version.workflows, version.runs]);
  if (!w) return <div className="flex h-[60vh] items-center justify-center"><Spinner /></div>;
  const ev = w.spec.evidence;
  const st = STATUS[w.status];
  const setStatus = async (s: string, msg: string) => {
    setBusy(s);
    try { setW(await api.patchWorkflow(id, { status: s })); toast(msg, "good"); refresh(); } finally { setBusy(null); }
  };

  return (
    <div className="mx-auto max-w-6xl px-4 pb-12 pt-5 sm:px-6 lg:pt-8">
      <Link to="/" className="mb-4 inline-flex items-center gap-1.5 text-sm text-mist hover:text-paper"><ArrowLeft className="h-4 w-4" />Workflows</Link>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <div className="min-w-0 space-y-5">
          <div>
            <Chip tone={st.tone}>{st.label}</Chip>
            <h1 className="mt-2 font-display text-4xl font-bold tracking-tight">{w.name}</h1>
            <p className="mt-2 text-mist">{w.intent}</p>
          </div>

          {w.status === "suggested" && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={softSpring} className="rounded-3xl border border-hand/35 bg-hand/[0.07] p-5">
              <p className="flex items-center gap-2 font-medium text-hand"><Sparkles className="h-4 w-4" />Why I'm suggesting this</p>
              <p className="mt-1 text-sm text-paper/90">
                You did these same steps <b>{ev.times_seen} times</b>, switching apps <b>{ev.app_switches} times</b> and spending about <b>{dur(ev.avg_manual_seconds)}</b> each time.
                Automated, it takes a few seconds and asks you only when something's unclear.
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button variant="primary" busy={busy === "active"} icon={<ShieldCheck className="h-4 w-4" />} onClick={() => setStatus("active", "Approved. For its first runs it shows you each change before making it")}>Approve and automate</Button>
                <Button busy={busy === "dismissed"} icon={<X className="h-4 w-4" />} onClick={async () => { await setStatus("dismissed", "Dismissed. I won't suggest it again"); nav("/"); }}>Not now</Button>
              </div>
            </motion.div>
          )}

          {w.status !== "suggested" && w.status !== "dismissed" && (
            <Autonomy w={w} onChange={(nw) => { setW(nw); refresh(); }} />
          )}

          {w.status !== "suggested" && (
            <div className="flex flex-wrap gap-2">
              {w.status === "active"
                ? <Button busy={busy === "paused"} icon={<Pause className="h-4 w-4" />} onClick={() => setStatus("paused", "Paused")}>Pause</Button>
                : <Button variant="primary" busy={busy === "active"} icon={<Play className="h-4 w-4" />} onClick={() => setStatus("active", "Active again")}>Resume</Button>}
              <Button busy={busy === "run"} icon={<Play className="h-4 w-4" />} onClick={async () => {
                setBusy("run");
                try { const r = await api.runNow(id); nav(`/run/${r.run_id}`); } catch (e) { toast((e as Error).message, "bad"); } finally { setBusy(null); }
              }}>{w.spec.trigger.type === "new_email" ? "Run on the latest email" : "Run now"}</Button>
            </div>
          )}

          <section>
            <h2 className="mb-2 font-display text-lg font-semibold">What I saw you do</h2>
            <div className="panel overflow-hidden rounded-2xl">
              {ev.examples.some((x) => x.customer) ? (
                <table className="w-full text-left text-sm">
                  <thead className="text-xs text-faint"><tr><th className="px-4 py-2 font-medium">When</th><th className="px-4 py-2 font-medium">Customer</th><th className="px-4 py-2 font-medium">Email subject</th><th className="px-4 py-2 text-right font-medium">Took you</th></tr></thead>
                  <tbody>
                    {[...ev.examples].reverse().map((x, i) => (
                      <tr key={i} className="border-t hairline">
                        <td className="whitespace-nowrap px-4 py-2 text-mist">{x.when ? when(x.when) : "-"}</td>
                        <td className="px-4 py-2">{x.customer}</td><td className="px-4 py-2 text-mist">{x.subject}</td>
                        <td className="whitespace-nowrap px-4 py-2 text-right text-mist">{dur(x.seconds)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <table className="w-full text-left text-sm">
                  <thead className="text-xs text-faint"><tr><th className="px-4 py-2 font-medium">When</th><th className="px-4 py-2 font-medium">Took you</th></tr></thead>
                  <tbody>
                    {ev.examples.map((x, i) => (
                      <tr key={i} className="border-t hairline"><td className="px-4 py-2">{x.when ? dayTime(x.when) : "-"}</td><td className="px-4 py-2 text-mist">{dur(x.seconds)}</td></tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            {ev.examples[0]?.message && (
              <p className="mt-2 text-xs text-faint">Latest 3 of the {ev.times_seen} times, newest first. You typed messages like: "{ev.examples[ev.examples.length - 1].message}". I turned that into a template.</p>
            )}
          </section>

          {!!w.learned.log?.length && (
            <section>
              <h2 className="mb-2 flex items-center gap-2 font-display text-lg font-semibold"><Brain className="h-4 w-4 text-volt" />Learned</h2>
              <ul className="space-y-1 text-sm text-mist">{w.learned.log.map((l, i) => <li key={i}>• {l}</li>)}</ul>
            </section>
          )}

          {runs.length > 0 && (
            <section>
              <h2 className="mb-2 font-display text-lg font-semibold">Runs</h2>
              <ul className="panel divide-y divide-white/[0.06] rounded-2xl">
                {runs.map((r) => (
                  <li key={r.id}>
                    <Link to={`/run/${r.id}`} className="flex items-center gap-3 px-4 py-2.5 text-sm hover:bg-white/[0.04]">
                      {r.status === "done" ? <CheckCircle2 className="h-4 w-4 text-ok" /> : r.status === "failed" ? <XCircle className="h-4 w-4 text-bad" /> :
                        r.status === "needs_you" ? <Hand className="h-4 w-4 text-hand" /> : r.status === "undone" ? <Undo2 className="h-4 w-4 text-mist" /> :
                          r.status === "cancelled" ? <XCircle className="h-4 w-4 text-faint" /> : <LoaderCircle className="h-4 w-4 animate-spin text-flow" />}
                      <span className="min-w-0 flex-1 truncate">{r.trigger.from}: {r.trigger.subject}</span>
                      <span className="text-xs text-faint">{Array.from(new Set(r.steps.map((s) => s.tier).filter(Boolean))).map((t) => TIER[t as string]?.label).join(", ")}</span>
                      <span className="text-xs text-faint">{timeAgo(r.started_at)}</span>
                    </Link>
                  </li>
                ))}
              </ul>
              {w.stats.runs ? <p className="mt-2 text-xs text-faint">{w.stats.succeeded}/{w.stats.runs} succeeded · saved {dur(w.stats.time_saved_sec)} so far</p> : null}
            </section>
          )}
        </div>

        <section className="panel h-fit min-w-0 rounded-3xl p-5 lg:sticky lg:top-6">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-display text-lg font-semibold">{proposal?.understood ? "The workflow, with your change" : "The workflow"}</h2>
            {!editing && <Button size="sm" variant="quiet" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setEditing(true)}>Edit</Button>}
          </div>
          {editing ? (
            <Editor spec={w.spec} onCancel={() => setEditing(false)} onSave={async (s) => {
              setW(await api.patchWorkflow(id, { spec: s })); setEditing(false); toast("Saved. I'll use your wording from now on", "good");
            }} />
          ) : (
            <>
              {w.status !== "dismissed" && <AskChange w={w} proposal={proposal} setProposal={setProposal} onApplied={(nw, p) => {
                setJustChanged(changedIds(w.spec, p.spec)); setW(nw); refresh();
                setTimeout(() => setJustChanged(undefined), 15000);
                setTimeout(() => document.querySelector("[data-changed='true']")?.scrollIntoView({ behavior: "smooth", block: "center" }), 300);
              }} />}
              <Pipeline spec={proposal?.understood ? proposal.spec : w.spec} changed={proposal?.understood ? changedIds(w.spec, proposal.spec) : justChanged} />
            </>
          )}
          {!editing && w.spec.variables.length > 0 && (
            <p className="mt-4 text-xs text-faint">
              Variables it fills in each time: {w.spec.variables.map((v) => <span key={v} className="mr-1"><Template text={`{{${v}}}`} /></span>)}
            </p>
          )}
        </section>
      </div>
    </div>
  );
}

function changedIds(a: Spec, b: Spec) {
  const old = Object.fromEntries(a.steps.map((s) => [s.id, JSON.stringify(s)]));
  return new Set(b.steps.filter((s) => old[s.id] !== JSON.stringify(s)).map((s) => s.id));
}
