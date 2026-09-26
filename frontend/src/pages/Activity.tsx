import { motion } from "framer-motion";
import { ArrowRight, Eye, Repeat } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import clsx from "clsx";
import AppGlyph from "../components/AppGlyph";
import { Chip, softSpring, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { clock, dayTime, describe, dur } from "../lib/format";
import { useApp } from "../lib/store";

type Sess = Awaited<ReturnType<typeof api.sessions>>[number];

export default function Activity() {
  const { version } = useApp();
  const [sessions, setSessions] = useState<Sess[] | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => { api.sessions().then(setSessions); }, [version.activity, version.workflows]);
  return (
    <div className="mx-auto max-w-4xl px-4 pb-12 pt-5 sm:px-6 lg:pt-10">
      <header className="mb-6">
        <p className="flex items-center gap-2 text-sm text-hand"><Eye className="h-4 w-4" />Observe → understand → detect repetition</p>
        <h1 className="mt-1 font-display text-4xl font-bold tracking-tight">What I observed</h1>
        <p className="mt-2 max-w-2xl text-mist">Your activity, split into tasks wherever you paused for a few minutes. Tasks that repeat a known routine are marked, with the matching steps highlighted.</p>
      </header>
      {!sessions ? <div className="flex justify-center py-16"><Spinner /></div> : (
        <>
        {[{ title: "Repeated routines", list: sessions.filter((x) => x.matched.length) },
          { title: "Everything else", list: sessions.filter((x) => !x.matched.length) }].map((grp) => grp.list.length > 0 && (
        <section key={grp.title} className="mb-8">
        <h2 className="mb-2 font-display text-lg font-semibold">{grp.title} <span className="text-faint">{grp.list.length}</span></h2>
        <ul className="space-y-2.5">
          {grp.list.map((s) => { const i = sessions.indexOf(s);
            const m = s.matched[0];
            const secs = (new Date(s.end).getTime() - new Date(s.start).getTime()) / 1000;
            const hit = new Set<number>();
            if (m) {
              // highlight events that belong to the matched tokens
              let k = 0;
              s.events.forEach((e, j) => { if (k < m.idx.length && s.tokens[m.idx[k]] === `${e.app}.${e.action}`) { hit.add(j); k++; } });
            }
            return (
              <motion.li key={s.start} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ ...softSpring, delay: Math.min(i, 8) * 0.03 }}
                className={clsx("panel overflow-hidden rounded-2xl", m && "border-hand/35")}>
                <button onClick={() => setOpen(open === i ? null : i)} className="flex w-full items-center gap-3 p-4 text-left" aria-expanded={open === i}>
                  <div className="flex -space-x-1.5">{s.apps.slice(0, 4).map((a) => <AppGlyph key={a} app={a} size="sm" />)}</div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{dayTime(s.start)} · {s.events.length} action{s.events.length === 1 ? "" : "s"} · {dur(secs)}</p>
                    <p className="truncate text-xs text-faint">{describe(s.events[0])}{s.events.length > 1 ? ` … ${describe(s.events[s.events.length - 1])}` : ""}</p>
                  </div>
                  {m && <Chip tone="hand"><Repeat className="h-3 w-3" />{m.name}</Chip>}
                </button>
                {open === i && (
                  <div className="border-t hairline px-4 pb-4 pt-2">
                    <ol className="space-y-1">
                      {s.events.map((e, j) => (
                        <li key={e.id} className={clsx("flex items-center gap-3 rounded-lg px-2 py-1 text-[13.5px]", hit.has(j) ? "bg-hand/10" : "opacity-60")}>
                          <span className="w-14 shrink-0 text-[11px] text-faint">{clock(e.ts)}</span>
                          <AppGlyph app={e.app} size="sm" />
                          <span className="min-w-0 flex-1 truncate">{describe(e)}</span>
                          <span className="text-[10px] text-faint">{e.source}</span>
                        </li>
                      ))}
                    </ol>
                    {m && <Link to={`/workflow/${m.id}`} className="mt-3 inline-flex items-center gap-1 text-sm text-hand">Open "{m.name}" <ArrowRight className="h-3.5 w-3.5" /></Link>}
                  </div>
                )}
              </motion.li>
            );
          })}
        </ul>
        </section>
        ))}
        </>
      )}
    </div>
  );
}
