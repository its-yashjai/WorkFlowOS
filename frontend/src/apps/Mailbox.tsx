import { motion } from "framer-motion";
import { Bot, Download, MailPlus, Paperclip } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import clsx from "clsx";
import { Button } from "../components/ui";
import { actorHeader, api } from "../lib/api";
import { initials, timeAgo } from "../lib/format";
import { useApp } from "../lib/store";
import type { Email } from "../lib/types";
import AppFrame from "./AppFrame";

export default function Mailbox() {
  const { version, toast } = useApp();
  const [mails, setMails] = useState<Email[]>([]);
  const [sel, setSel] = useState<Email | null>(null);
  useEffect(() => { api.mail().then(setMails); }, [version.apps, version.runs]);
  useEffect(() => { const id = new URLSearchParams(location.search).get("email"); if (id) api.openMail(Number(id)).then(setSel); }, []);
  const open = async (m: Email) => { setSel(await api.openMail(m.id)); setMails((ms) => ms.map((x) => (x.id === m.id ? { ...x, read: 1 } : x))); };
  return (
    <AppFrame app="mail" right={
      <Button size="sm" icon={<MailPlus className="h-4 w-4" />} onClick={async () => {
        const r = await api.testEmail();
        toast(r.runs.length ? "New email arrived. A workflow picked it up" : "New email arrived", "good");
      }}>Simulate new email</Button>}>
      <div className="grid h-full lg:grid-cols-[380px_1fr]">
        <ul className={clsx("scroll-thin overflow-y-auto border-r hairline", sel && "hidden lg:block")}>
          {mails.map((m) => (
            <li key={m.id}>
              <button onClick={() => open(m)} className={clsx("flex w-full gap-3 border-b hairline px-4 py-3 text-left hover:bg-white/[0.04]", sel?.id === m.id && "bg-white/[0.06]")}>
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-white/10 text-xs font-bold">{initials(m.sender_name)}</span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center justify-between gap-2">
                    <span className={clsx("truncate text-sm", !m.read && "font-semibold")}>{m.sender_name}</span>
                    <span className="shrink-0 text-[11px] text-faint">{timeAgo(m.received_at)}</span>
                  </span>
                  <span className={clsx("block truncate text-sm", m.read ? "text-mist" : "text-paper")}>{m.subject}</span>
                  <span className="mt-1 flex items-center gap-2">
                    {m.source === "gmail" && <span className="rounded bg-[#E8544E]/15 px-1.5 text-[11px] font-medium text-[#FF8A84]">Gmail</span>}
                    {m.attachment && <span className="inline-flex items-center gap-1 text-[11px] text-faint"><Paperclip className="h-3 w-3" />{m.attachment}</span>}
                    {!!m.handled_by && <span className="inline-flex items-center gap-1 rounded bg-flow/15 px-1.5 text-[11px] text-flow"><Bot className="h-3 w-3" />Handled</span>}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
        <div className={clsx("scroll-thin overflow-y-auto p-5 sm:p-8", !sel && "hidden lg:block")}>
          {!sel ? <p className="text-mist">Select an email.</p> : (
            <motion.article key={sel.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
              <button className="mb-3 text-sm text-mist lg:hidden" onClick={() => setSel(null)}>← Inbox</button>
              <h2 data-testid="mail-subject" className="font-display text-2xl font-bold">{sel.subject}</h2>
              <p data-testid="mail-from" data-name={sel.sender_name} data-email={sel.sender_email} className="mt-1 text-sm text-mist">{sel.sender_name} &lt;{sel.sender_email}&gt;</p>
              <p className="mt-6 whitespace-pre-wrap leading-relaxed">{sel.body}</p>
              {sel.attachment && (
                <a data-testid="mail-attachment" data-name={sel.attachment} href={`/api/apps/mail/${sel.id}/attachment${actorHeader()["X-Actor"] ? "?actor=automation" : ""}`} download={sel.attachment} className="mt-6 inline-flex items-center gap-3 rounded-2xl border hairline bg-white/[0.04] p-3 pr-4 hover:bg-white/[0.08]">
                  <span className="grid h-10 w-10 place-items-center rounded-xl bg-[#E8544E]/15 text-xs font-bold text-[#FF8A84]">PDF</span>
                  <span className="text-sm">{sel.attachment}</span><Download className="h-4 w-4 text-mist" />
                </a>
              )}
              {!!sel.handled_by && <p className="mt-6 text-sm text-flow">Handled automatically. <Link className="underline" to={`/run/${sel.handled_by}`}>See the run</Link></p>}
            </motion.article>
          )}
        </div>
      </div>
    </AppFrame>
  );
}
