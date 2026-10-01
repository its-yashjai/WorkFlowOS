import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, BookUser, Eye, ExternalLink, Hand, MessagesSquare, PartyPopper, Undo2, UserPlus, XCircle } from "lucide-react";
import { Fragment, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import clsx from "clsx";
import Pipeline from "../components/Pipeline";
import { Button, Chip, softSpring, Spinner, Toggle } from "../components/ui";
import { api } from "../lib/api";
import { clock, dur } from "../lib/format";
import { useApp } from "../lib/store";
import type { Customer, Run, Spec, Workflow } from "../lib/types";
import AppGlyph from "../components/AppGlyph";

function Preview({ run, onDone }: { run: Run; onDone: () => void }) {
  const changes = run.note.changes || [];
  const [vals, setVals] = useState<Record<string, Record<string, string>>>(() =>
    Object.fromEntries(changes.map((c) => [c.step, Object.fromEntries(c.fields.map((f) => [f.key, f.value]))])));
  const [busy, setBusy] = useState<string | null>(null);
  const edited = changes.some((c) => c.fields.some((f) => vals[c.step]?.[f.key] !== f.value));
  const go = async (cancel = false) => {
    setBusy(cancel ? "c" : "a");
    try { await api.resolve(run.id, cancel ? { cancel: true } : { edits: vals }); onDone(); } finally { setBusy(null); }
  };
  return (
    <motion.div initial={{ opacity: 0, y: 10, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={softSpring}
      className="rounded-3xl border border-volt/45 bg-volt/[0.07] p-5">
      <p className="flex items-center gap-2 font-display text-lg font-semibold text-volt"><Eye className="h-5 w-5" />Here's what I'm about to change</p>
      <p className="mt-1 text-sm text-mist">Nothing has been changed yet. This workflow is still earning your trust, so it shows you first. Fix anything that's off.</p>
      <div className="mt-4 space-y-3">
        {changes.map((c) => (
          <div key={c.step} className="rounded-2xl border border-white/10 bg-ink/40 p-3">
            <p className="flex items-center gap-2 text-sm font-medium"><AppGlyph app={c.app} size="sm" />{c.where}</p>
            {c.last_note && <p className="mt-2 text-xs text-faint">Currently the latest note: "{c.last_note}"</p>}
            {c.fields.map((f) => f.readonly ? (
              f.value ? <p key={f.key} className="mt-2 text-xs text-mist">{f.label}: <span className="text-paper">{f.value}</span></p> : null
            ) : (
              <label key={f.key} className="mt-2 block text-xs text-mist">
                <span className="text-ok">+ </span>{f.label}
                <textarea rows={2} value={vals[c.step]?.[f.key] ?? ""} aria-label={f.label}
                  onChange={(e) => setVals((v) => ({ ...v, [c.step]: { ...v[c.step], [f.key]: e.target.value } }))}
                  className="mt-1 w-full resize-none rounded-lg border border-ok/25 bg-ok/[0.05] px-2 py-1.5 text-sm text-paper outline-none focus:border-volt" />
              </label>
            ))}
          </div>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <Button variant="primary" busy={busy === "a"} onClick={() => go()}>{edited ? "Use my version" : "Looks right, go"}</Button>
        <Button variant="quiet" busy={busy === "c"} icon={<XCircle className="h-4 w-4" />} onClick={() => go(true)}>Cancel run</Button>
      </div>
    </motion.div>
  );
}

function YourTurn({ run, onDone }: { run: Run; onDone: () => void }) {
  const n = run.note;
  const [busy, setBusy] = useState(false);
  return (
    <motion.div initial={{ opacity: 0, y: 10, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={softSpring}
      className="rounded-3xl border border-hand/45 bg-hand/[0.08] p-5">
      <p className="flex items-center gap-2 font-display text-lg font-semibold text-hand"><Hand className="h-5 w-5" />Your turn for one step</p>
      <p className="mt-1 text-sm">I can't do <b>{n.label}</b> safely by myself, so I paused here. Do it, then I'll carry on with the rest.</p>
      {n.hint && <p className="mt-2 text-xs text-mist">{n.hint}</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        {n.url && <a href={n.url} target="_blank" rel="noreferrer"><Button icon={<ExternalLink className="h-4 w-4" />}>Open the page</Button></a>}
        <Button variant="primary" busy={busy} onClick={async () => { setBusy(true); try { await api.resolve(run.id, { remember: false }); onDone(); } finally { setBusy(false); } }}>Done, continue</Button>
      </div>
    </motion.div>
  );
}

function NeedsYou({ run, onDone }: { run: Run; onDone: () => void }) {
  const n = run.note;
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [pick, setPick] = useState<number | "">(n.suggested ?? "");
  const [remember, setRemember] = useState(true);
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false);
  const [company, setCompany] = useState("");
  useEffect(() => { api.crm().then(setCustomers); }, []);
  const go = async (b: Parameters<typeof api.resolve>[1]) => { setBusy(true); try { await api.resolve(run.id, { ...b, remember }); onDone(); } finally { setBusy(false); } };
  return (
    <motion.div initial={{ opacity: 0, y: 10, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={softSpring}
      className="rounded-3xl border border-hand/45 bg-hand/[0.08] p-5">
      <p className="flex items-center gap-2 font-display text-lg font-semibold text-hand"><Hand className="h-5 w-5" />I need you for one thing</p>
      <p className="mt-1 text-sm">{n.reason}. {n.suggested_name ? <>Same domain as <b>{n.suggested_name}</b>. Is it them?</> : "Which customer is this?"}</p>
      {!creating ? (
        <div className="mt-4 space-y-3">
          <select value={pick} onChange={(e) => setPick(e.target.value ? Number(e.target.value) : "")} aria-label="Customer"
            className="h-10 w-full rounded-xl border border-white/15 bg-ink-3 px-3 text-sm">
            <option value="">Choose a customer…</option>
            {customers.map((c) => <option key={c.id} value={c.id}>{c.name} · {c.company}</option>)}
          </select>
          <label className="flex items-center gap-3 text-sm">
            <Toggle label="Remember" on={remember} onChange={setRemember} />
            Remember that {n.email} belongs to this customer
          </label>
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" busy={busy} disabled={!pick} onClick={() => go({ customer_id: Number(pick) })}>Continue the run</Button>
            <Button icon={<UserPlus className="h-4 w-4" />} onClick={() => setCreating(true)}>New customer instead</Button>
          </div>
        </div>
      ) : (
        <form className="mt-4 space-y-2" onSubmit={(e) => { e.preventDefault(); go({ create: { name: n.name || "", email: n.email || "", company } }); }}>
          <p className="text-sm text-mist">Create <b className="text-paper">{n.name}</b> ({n.email}) in the CRM:</p>
          <input value={company} onChange={(e) => setCompany(e.target.value)} placeholder="Company" required
            className="h-10 w-full rounded-xl border border-white/15 bg-ink-3 px-3 text-sm outline-none focus:border-volt" />
          <div className="flex gap-2"><Button variant="primary" busy={busy}>Create and continue</Button><Button type="button" variant="quiet" onClick={() => setCreating(false)}>Back</Button></div>
        </form>
      )}
    </motion.div>
  );
}

export default function RunPage() {
  const id = Number(useParams().id);
  const { version } = useApp();
  const [run, setRun] = useState<Run | null>(null);
  const [wf, setWf] = useState<Workflow | null>(null);
  const load = () => api.run(id).then(setRun);
  useEffect(() => { load(); }, [id, version.runs]);
  useEffect(() => { if (run && (!wf || wf.id !== run.workflow_id)) api.workflow(run.workflow_id).then((r) => setWf(r.workflow)); }, [run?.workflow_id]);
  useEffect(() => { if (run?.status !== "running") return; const t = setInterval(load, 700); return () => clearInterval(t); }, [run?.status, id]);
  if (!run || !wf) return <div className="flex h-[60vh] items-center justify-center"><Spinner /></div>;
  const secs = run.finished_at ? (new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000 : null;
  const manual = wf.pattern.avg_seconds;
  const tone = ({ running: "flow", done: "ok", failed: "bad", needs_you: run.note.kind === "preview" ? "volt" : "hand", undone: "mist", cancelled: "mist" } as const)[run.status];
  const word = { running: "Running", done: "Done", failed: "Failed", needs_you: run.note.kind === "preview" ? "Preview: waiting for your OK" : "Waiting for you", undone: "Undone", cancelled: "Cancelled" }[run.status];

  return (
    <div className="mx-auto max-w-5xl px-4 pb-12 pt-5 sm:px-6 lg:pt-8">
      <Link to={`/workflow/${wf.id}`} className="mb-4 inline-flex items-center gap-1.5 text-sm text-mist hover:text-paper"><ArrowLeft className="h-4 w-4" />{wf.name}</Link>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        <div className="min-w-0 space-y-5">
          <div>
            <Chip tone={tone}>{word}</Chip>
            <h1 className="mt-2 font-display text-3xl font-bold tracking-tight">{run.trigger.subject}</h1>
            <p className="mt-1 text-mist">From {run.trigger.from} · started {clock(run.started_at)}</p>
          </div>
          <AnimatePresence mode="wait">
            {run.status === "needs_you" && (run.note.kind === "preview" ? <Preview key={`p${run.id}`} run={run} onDone={load} />
              : run.note.kind === "manual" ? <YourTurn key="m" run={run} onDone={load} /> : <NeedsYou key="n" run={run} onDone={load} />)}
            {(run.status === "undone" || run.status === "cancelled") && (
              <motion.div key="u" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="rounded-3xl border border-white/15 bg-white/[0.04] p-5 text-sm">
                <p className="flex items-center gap-2 font-display text-lg font-semibold"><Undo2 className="h-5 w-5 text-mist" />{run.status === "undone" ? "Undone" : "Cancelled"}</p>
                <p className="mt-1 text-mist">{run.status === "undone"
                  ? "Every change this run made was rolled back. The workflow will show you changes before making them again."
                  : "You cancelled before anything was changed."}</p>
              </motion.div>
            )}
            {run.status === "done" && (
              <motion.div key="d" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={softSpring}
                className="rounded-3xl border border-ok/35 bg-ok/[0.07] p-5">
                <p className="flex items-center gap-2 font-display text-lg font-semibold text-ok"><PartyPopper className="h-5 w-5" />Done in {dur(secs ?? 0)}</p>
                <p className="mt-1 text-sm">By hand this took you about <b>{dur(manual)}</b> and {wf.pattern.switches} app switches.</p>
                <div className="mt-4 flex flex-wrap gap-2">
                  {!!run.vars.customer_id && <Link to={`/apps/crm?customer=${run.vars.customer_id}`}><Button size="sm" icon={<BookUser className="h-4 w-4" />}>See the CRM record</Button></Link>}
                  {run.steps.some((s) => s.status === "done" && s.detail.startsWith("Posted in #")) && <Link to={`/apps/chat?channel=${(run.steps.find((s) => s.status === "done" && s.detail.startsWith("Posted in #"))?.detail.split("#")[1] || "support").trim()}`}><Button size="sm" icon={<MessagesSquare className="h-4 w-4" />}>See the Huddle message</Button></Link>}
                  {run.steps.some((s) => s.undo) && <UndoButton id={run.id} onDone={load} />}
                </div>
                {run.steps.some((s) => s.healed?.length) && <p className="mt-3 text-xs text-volt">The app's screen changed during this run. I found the new buttons and fields by what they mean, and I'll use them next time.</p>}
              </motion.div>
            )}
            {run.status === "failed" && (
              <motion.div key="f" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="rounded-3xl border border-bad/35 bg-bad/[0.07] p-5 text-sm">
                Every automation method failed for one step. Nothing was half-done silently. Check the step on the right, then run it again.
                {run.steps.some((s) => s.undo) && (
                  <div className="mt-3 flex flex-wrap items-center gap-3">
                    <span className="text-mist">The steps before it did make changes. You can roll those back.</span>
                    <UndoButton id={run.id} onDone={load} />
                  </div>
                )}
              </motion.div>
            )}
          </AnimatePresence>
          <div className="panel rounded-2xl p-4 text-sm">
            <p className="mb-2 font-medium">How each step runs</p>
            <ol className="space-y-1 text-mist">
              <li>1. <b className="text-paper">API</b>: most reliable, used first</li>
              <li>2. <b className="text-paper">App integration</b>: the app's own SDK</li>
              <li>3. <b className="text-paper">Browser automation</b>: Playwright drives the real web page</li>
              <li>4. <b className="text-paper">Self-healing</b>: if the screen changed, finds the button or field by what it means</li>
              <li>5. <b className="text-paper">You</b>: when it isn't sure, it stops and asks</li>
            </ol>
            <p className="mt-2 text-xs text-faint">Crossed-out badges show a method that failed before the next one took over.</p>
          </div>
          {Object.keys(run.vars).length > 0 && (
            <div className="panel rounded-2xl p-4 text-sm">
              <p className="mb-2 font-medium">What it filled in</p>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
                {Object.entries(run.vars).filter(([k, v]) => v && !k.startsWith("_") && !["email_id"].includes(k)).map(([k, v]) => (
                  <Fragment key={k}><dt className="text-faint">{k.replace(/_/g, " ")}</dt><dd className="truncate">{String(v)}</dd></Fragment>
                ))}
              </dl>
            </div>
          )}
        </div>
        <section className={clsx("panel h-fit min-w-0 rounded-3xl p-5", run.status === "running" && "shadow-[0_0_60px_-20px_rgba(52,214,196,0.45)]")}>
          <h2 className="mb-4 font-display text-lg font-semibold">Live run</h2>
          <Pipeline spec={(run.vars._spec as Spec | undefined) ?? wf.spec} run={run.steps} compact />
        </section>
      </div>
    </div>
  );
}

function UndoButton({ id, onDone }: { id: number; onDone: () => void }) {
  const { toast } = useApp();
  const [busy, setBusy] = useState(false);
  return (
    <Button size="sm" variant="danger" busy={busy} icon={<Undo2 className="h-4 w-4" />} onClick={async () => {
      setBusy(true);
      try { await api.undo(id); toast("Rolled back everything this run changed", "good"); onDone(); }
      catch (e) { toast((e as Error).message, "bad"); } finally { setBusy(false); }
    }}>Undo this run</Button>
  );
}
