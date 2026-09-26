import { motion } from "framer-motion";
import { Bot, Hash, Send } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import clsx from "clsx";
import { api } from "../lib/api";
import { clock, initials } from "../lib/format";
import { useApp } from "../lib/store";
import type { ChatMsg } from "../lib/types";
import AppFrame from "./AppFrame";

export default function Huddle() {
  const { version, state } = useApp();
  const v2 = state?.settings.ui_v2 === "1";
  const init = new URLSearchParams(location.search).get("channel");
  const [channel, setChannel] = useState(init ? "#" + init.replace(/^#/, "") : "#support");
  const [chs, setChs] = useState<{ channel: string; n: number }[]>([]);
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const load = (open = false) => fetch(`/api/apps/chat?channel=${encodeURIComponent(channel)}${open ? "&open=1" : ""}`, {
    headers: new URLSearchParams(location.search).get("actor") === "automation" ? { "X-Actor": "automation" } : {},
  }).then((r) => r.json()).then((d) => { setChs(d.channels); setMsgs(d.messages); });
  useEffect(() => { load(true); }, [channel]);
  useEffect(() => { load(false); }, [version.apps]);
  useLayoutEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [msgs.length]);
  const send = async () => { if (!text.trim()) return; await api.postChat(channel, text.trim()); setText(""); load(); };
  return (
    <AppFrame app="chat">
      <div className="grid h-full grid-cols-[88px_1fr] sm:grid-cols-[200px_1fr]">
        <ul className="border-r hairline p-2">
          {chs.map((c) => (
            <li key={c.channel}>
              <button onClick={() => setChannel(c.channel)} className={clsx("flex w-full items-center gap-1.5 rounded-lg px-2 py-2 text-left text-sm", channel === c.channel ? "bg-white/[0.08] text-paper" : "text-mist hover:bg-white/[0.04]")}>
                <Hash className="h-3.5 w-3.5 shrink-0" /><span className="truncate">{c.channel.slice(1)}</span>
              </button>
            </li>
          ))}
        </ul>
        <div className="flex min-h-0 flex-col">
          <div className="scroll-thin min-h-0 flex-1 space-y-3 overflow-y-auto p-4 sm:p-6">
            {msgs.map((m) => (
              <motion.div key={m.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex gap-3">
                <span className={clsx("grid h-9 w-9 shrink-0 place-items-center rounded-xl text-xs font-bold", m.bot ? "bg-flow/15 text-flow" : "bg-white/10")}>
                  {m.bot ? <Bot className="h-4 w-4" /> : initials(m.author)}
                </span>
                <div className="min-w-0">
                  <p className="text-sm"><b className={m.bot ? "text-flow" : ""}>{m.author}</b> <span className="text-xs text-faint">{clock(m.ts)}</span></p>
                  <p className="text-[14.5px]">{m.text.split(/(@[A-Za-z]+)/g).map((p, k) => p.startsWith("@") ? <span key={k} className="rounded bg-volt/20 px-1 font-medium text-volt">{p}</span> : p)}</p>
                </div>
              </motion.div>
            ))}
            {msgs.length === 0 && <p className="text-sm text-faint">No messages in {channel} yet.</p>}
            <div ref={end} />
          </div>
          <div className="border-t hairline p-3">
            <div className="flex items-center gap-2 rounded-xl border border-white/12 bg-ink/50 p-1.5 pl-3 focus-within:border-volt">
              <input data-testid={v2 ? undefined : "chat-input"} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") send(); }}
                placeholder={v2 ? "Write to the team…" : `Message ${channel}`} aria-label={v2 ? undefined : "Message"} className="h-9 min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-faint" />
              <button onClick={send} aria-label="Send" className="grid h-9 w-9 place-items-center rounded-lg bg-volt text-ink"><Send className="h-4 w-4" /></button>
            </div>
          </div>
        </div>
      </div>
    </AppFrame>
  );
}
