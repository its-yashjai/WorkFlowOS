import { motion } from "framer-motion";
import { Bot, FileText, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { Button, Chip } from "../components/ui";
import { api } from "../lib/api";
import { initials, timeAgo } from "../lib/format";
import { useApp } from "../lib/store";
import type { Customer } from "../lib/types";
import AppFrame from "./AppFrame";

export default function Ledger() {
  const { version, state } = useApp();
  const v2 = state?.settings.ui_v2 === "1"; // "Ledger 2.0" redesign: new labels, no test ids
  const params = new URLSearchParams(location.search);
  const [q, setQ] = useState("");
  const [list, setList] = useState<Customer[]>([]);
  const [sel, setSel] = useState<Customer | null>(null);
  const [note, setNote] = useState("");
  const [att, setAtt] = useState("");
  const [saved, setSaved] = useState(false);
  const timer = useRef<number>();
  useEffect(() => { api.crm("").then(setList); }, [version.apps]);
  useEffect(() => { const c = params.get("customer"); if (c) api.customer(Number(c)).then(setSel); }, []);
  useEffect(() => { if (sel) api.customer(sel.id, true).then(setSel); }, [version.apps]);
  const search = (v: string) => {
    setQ(v);
    clearTimeout(timer.current);
    timer.current = window.setTimeout(() => api.crm(v).then(setList), 450); // debounced so one search = one observed action
  };
  const save = async () => {
    if (!sel || !note.trim()) return;
    setSel(await api.updateCustomer(sel.id, note.trim(), att.trim()));
    setNote(""); setAtt(""); setSaved(true); setTimeout(() => setSaved(false), 2500);
  };
  return (
    <AppFrame app="crm">
      <div className="grid h-full lg:grid-cols-[340px_1fr]">
        <div className={clsx("flex min-h-0 flex-col border-r hairline", sel && "hidden lg:flex")}>
          <label className="m-3 flex items-center gap-2 rounded-xl border border-white/12 bg-white/[0.04] px-3">
            <Search className="h-4 w-4 text-faint" />
            <input value={q} onChange={(e) => search(e.target.value)} data-testid="crm-search" placeholder="Search customers" aria-label="Search customers" className="h-10 flex-1 bg-transparent text-sm outline-none placeholder:text-faint" />
          </label>
          <ul className="scroll-thin min-h-0 flex-1 overflow-y-auto">
            {list.map((c) => (
              <li key={c.id}>
                <button data-testid="crm-row" data-id={c.id} data-email={c.email} data-name={c.name} data-company={c.company} onClick={async () => setSel(await api.customer(c.id))} className={clsx("flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-white/[0.04]", sel?.id === c.id && "bg-white/[0.06]")}>
                  <span className="grid h-9 w-9 place-items-center rounded-full bg-volt/15 text-xs font-bold text-volt">{initials(c.company)}</span>
                  <span className="min-w-0"><span className="block truncate text-sm font-medium">{c.company}</span><span className="block truncate text-xs text-faint">{c.name} · {c.email}</span></span>
                </button>
              </li>
            ))}
          </ul>
        </div>
        <div className={clsx("scroll-thin overflow-y-auto p-5 sm:p-8", !sel && "hidden lg:block")}>
          {!sel ? <p className="text-mist">Search or pick a customer.</p> : (
            <motion.div key={sel.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="max-w-2xl">
              <button className="mb-3 text-sm text-mist lg:hidden" onClick={() => setSel(null)}>← Customers</button>
              <div className="flex items-center gap-3">
                <h2 className="font-display text-3xl font-bold">{sel.company}</h2><Chip tone="volt">{sel.tier}</Chip>
              </div>
              <p className="text-sm text-mist">{sel.name} · {sel.email}</p>
              {v2 ? (
                <div className="mt-6 rounded-2xl border border-volt/30 bg-volt/[0.06] p-4">
                  <p className="mb-3 flex items-center gap-2 text-sm font-medium"><Chip tone="volt">Ledger 2.0</Chip>Log an interaction</p>
                  <div className="flex flex-col gap-2 sm:flex-row-reverse">
                    <Button variant="good" size="sm" className="h-10 shrink-0" onClick={save}>Update record</Button>
                    <input value={att} onChange={(e) => setAtt(e.target.value)} placeholder="Linked document (optional)"
                      className="h-10 min-w-0 flex-1 rounded-xl border border-white/12 bg-ink/60 px-3 text-sm outline-none focus:border-volt" />
                  </div>
                  <textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Describe the customer's request"
                    className="mt-2 w-full resize-none rounded-xl border border-white/12 bg-ink/60 px-3 py-2 text-sm outline-none focus:border-volt" />
                </div>
              ) : (
              <div className="panel mt-6 rounded-2xl p-4">
                <p className="mb-2 text-sm font-medium">Add to record</p>
                <textarea data-testid="crm-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="What did the customer ask for?"
                  className="w-full resize-none rounded-xl border border-white/12 bg-ink/60 px-3 py-2 text-sm outline-none focus:border-volt" />
                <div className="mt-2 flex gap-2">
                  <input data-testid="crm-attachment" value={att} onChange={(e) => setAtt(e.target.value)} placeholder="Attachment file name (optional)"
                    className="h-9 min-w-0 flex-1 rounded-xl border border-white/12 bg-ink/60 px-3 text-sm outline-none focus:border-volt" />
                  <Button data-testid="crm-save" variant="primary" size="sm" className="h-9" onClick={save}>Save</Button>
                </div>
              </div>
              )}
              {saved && <p data-testid="crm-saved" className="mt-2 text-sm text-ok">Saved to {sel.company}</p>}
              {sel.files.length > 0 && (
                <div className="mt-6">
                  <p className="mb-2 text-sm font-medium">Files</p>
                  <div className="flex flex-wrap gap-2">{sel.files.map((f) => <span key={f} className="inline-flex items-center gap-1.5 rounded-lg bg-white/[0.05] px-2 py-1 text-xs"><FileText className="h-3.5 w-3.5 text-mist" />{f}</span>)}</div>
                </div>
              )}
              <p className="mb-2 mt-6 text-sm font-medium">Activity</p>
              <ul className="space-y-2">
                {sel.notes.map((n, i) => (
                  <motion.li key={n.ts + i} initial={i === 0 ? { opacity: 0, x: -8 } : false} animate={{ opacity: 1, x: 0 }}
                    className={clsx("rounded-2xl border p-3 text-sm", n.by === "WorkFlowOS" ? "border-flow/30 bg-flow/[0.05]" : "hairline bg-white/[0.02]")}>
                    <p>{n.text}</p>
                    <p className="mt-1 flex items-center gap-1.5 text-xs text-faint">{n.by === "WorkFlowOS" && <Bot className="h-3 w-3 text-flow" />}{n.by} · {timeAgo(n.ts)}{n.attachment ? ` · ${n.attachment}` : ""}</p>
                  </motion.li>
                ))}
                {sel.notes.length === 0 && <li className="text-sm text-faint">No activity yet.</li>}
              </ul>
            </motion.div>
          )}
        </div>
      </div>
    </AppFrame>
  );
}
