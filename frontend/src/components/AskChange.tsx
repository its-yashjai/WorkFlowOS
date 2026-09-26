import { AnimatePresence, motion } from "framer-motion";
import { Check, Cpu, Minus, Plus, ShieldCheck, Sparkles, Undo2 } from "lucide-react";
import { useState } from "react";
import clsx from "clsx";
import { api } from "../lib/api";
import { useApp } from "../lib/store";
import type { AskResult, Workflow } from "../lib/types";
import { Button, softSpring } from "./ui";

const EXAMPLES = [
  "Only notify #finance if the attachment is an invoice, and tag Priya",
  "Also post in #sales",
  "Skip the chat message when the subject mentions test",
];

/** Change a workflow by saying it. The proposal is shown as a diff; nothing is saved until you apply it. */
export default function AskChange({ w, proposal, setProposal, onApplied }: {
  w: Workflow; proposal: AskResult | null; setProposal: (p: AskResult | null) => void; onApplied: (w: Workflow, p: AskResult) => void;
}) {
  const [saved, setSaved] = useState<AskResult | null>(null);
  const { state, toast } = useApp();
  const [text, setText] = useState("");
  const [asked, setAsked] = useState("");
  const [busy, setBusy] = useState(false);
  const [applying, setApplying] = useState(false);
  const ai = state?.ai;
  const ask = async (t = text) => {
    if (!t.trim() || busy) return;
    setBusy(true); setAsked(t.trim()); setProposal(null); setSaved(null);
    try { setProposal(await api.ask(w.id, t.trim())); } catch (e) { toast((e as Error).message, "bad"); } finally { setBusy(false); }
  };
  const apply = async () => {
    if (!proposal) return;
    setApplying(true);
    try {
      const nw = await api.patchWorkflow(w.id, { spec: proposal.spec, said: asked });
      const p = proposal;
      setProposal(null); setText(""); setSaved(p); onApplied(nw, p); toast("Saved. The workflow is updated", "good");
    } finally { setApplying(false); }
  };
  const engineLine = (p: AskResult) => p.engine === "ollama" ? `On-device AI · ${p.model} · ${(p.ms / 1000).toFixed(1)}s · nothing left this computer`
    : p.engine === "groq" ? `Cloud AI · Groq · ${(p.ms / 1000).toFixed(1)}s` : "Built-in parser · instant · offline";

  return (
    <div className="mb-5 rounded-2xl border border-volt/30 bg-volt/[0.05] p-3">
      <p className="mb-2 flex items-center justify-between gap-2 text-sm font-medium">
        <span className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-volt" />Change it by saying it</span>
        {ai && <span className={clsx("inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px]", ai.local ? "bg-ok/15 text-ok" : "bg-hand/15 text-hand")}>
          {ai.local ? <ShieldCheck className="h-3 w-3" /> : <Cpu className="h-3 w-3" />}{ai.engine === "ollama" ? `On-device · ${ai.model}` : ai.engine === "groq" ? "Cloud AI" : "Offline rules"}
        </span>}
      </p>
      <form onSubmit={(e) => { e.preventDefault(); ask(); }} className="flex gap-2">
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. only notify #finance for invoices and tag Priya" aria-label="Describe a change"
          className="h-10 min-w-0 flex-1 rounded-xl border border-white/12 bg-ink/60 px-3 text-sm outline-none placeholder:text-faint focus:border-volt" />
        <Button variant="primary" size="sm" className="h-10" busy={busy} disabled={!text.trim()}>Propose</Button>
      </form>
      {!proposal && !busy && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {EXAMPLES.map((x) => (
            <button key={x} type="button" onClick={() => { setText(x); ask(x); }}
              className="rounded-lg bg-white/[0.05] px-2 py-1 text-left text-[11.5px] text-mist hover:bg-white/10 hover:text-paper">{x}</button>
          ))}
        </div>
      )}
      <AnimatePresence mode="wait">
        {saved && !busy && !proposal && (
          <motion.div key="s" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
            className="mt-3 rounded-xl border border-ok/40 bg-ok/[0.08] p-3">
            <p className="flex items-center gap-2 text-sm font-semibold text-ok"><Check className="h-4 w-4" />Saved. The workflow now does this:</p>
            <ul className="mt-1.5 space-y-0.5 text-[13px] text-paper/90">{saved.changes.map((c, i) => <li key={i}>• {c.text}</li>)}</ul>
            <p className="mt-1.5 text-[11px] text-faint">Changed steps are highlighted in green below. The next run uses them.</p>
          </motion.div>
        )}
        {busy && (
          <motion.p key="t" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="mt-3 flex items-center gap-2 text-sm text-mist">
            <motion.span className="h-2 w-2 rounded-full bg-volt" animate={{ opacity: [1, 0.2, 1] }} transition={{ duration: 1, repeat: Infinity }} />
            {ai?.engine === "ollama" ? `Thinking on this computer with ${ai.model}…` : ai?.engine === "groq" ? "Asking Groq…" : "Reading your request…"}
          </motion.p>
        )}
        {proposal && (
          <motion.div key="p" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={softSpring} className="mt-3">
            {proposal.understood ? (
              <>
                <p className="text-xs text-faint">Proposed changes (the workflow on the right is the new version, changed steps in green):</p>
                <ul className="mt-1.5 space-y-1">
                  {proposal.changes.map((c, i) => (
                    <li key={i} className={clsx("flex items-start gap-2 rounded-lg px-2 py-1 text-[13px]",
                      c.kind === "add" ? "bg-ok/[0.08] text-ok" : c.kind === "remove" ? "bg-bad/[0.08] text-bad" : "bg-hand/[0.08] text-hand")}>
                      {c.kind === "add" ? <Plus className="mt-0.5 h-3.5 w-3.5 shrink-0" /> : c.kind === "remove" ? <Minus className="mt-0.5 h-3.5 w-3.5 shrink-0" /> : <Check className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
                      <span className="text-paper/90">{c.text}</span>
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-[11px] text-faint">{engineLine(proposal)}{proposal.note ? ` · ${proposal.note}` : ""}</p>
                <div className="mt-3 flex gap-2">
                  <Button variant="good" size="sm" busy={applying} onClick={apply}>Apply changes</Button>
                  <Button variant="quiet" size="sm" icon={<Undo2 className="h-3.5 w-3.5" />} onClick={() => setProposal(null)}>Discard</Button>
                </div>
              </>
            ) : (
              <p className="text-sm text-mist">I couldn't turn that into a change to this workflow. Try naming a channel (#finance), a person to tag, or a condition like "only if the attachment is an invoice".</p>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
