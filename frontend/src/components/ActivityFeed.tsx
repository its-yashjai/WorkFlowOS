import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { when, describe } from "../lib/format";
import { useApp } from "../lib/store";
import type { WfEvent } from "../lib/types";
import AppGlyph from "./AppGlyph";
import { spring } from "./ui";

/** Live stream of what the observers recorded. New events slide in. */
export default function ActivityFeed({ limit = 12 }: { limit?: number }) {
  const { version } = useApp();
  const [evs, setEvs] = useState<WfEvent[] | null>(null);
  useEffect(() => { api.events(limit).then(setEvs).catch(() => {}); }, [version.activity, version.workflows, limit]);
  if (!evs) return <p className="p-4 text-sm text-faint">Loading…</p>;
  if (!evs.length) return <p className="p-4 text-sm text-mist">Nothing observed yet. Use the apps on the left, or run the desktop agent.</p>;
  return (
    <ul className="space-y-1">
      <AnimatePresence initial={false}>
        {evs.map((e) => (
          <motion.li key={e.id} layout initial={{ opacity: 0, x: -14, backgroundColor: "rgba(255,181,71,0.14)" }}
            animate={{ opacity: 1, x: 0, backgroundColor: "rgba(255,181,71,0)" }} transition={{ ...spring, backgroundColor: { duration: 1.6 } }}
            className="flex items-center gap-3 rounded-xl px-2 py-1.5">
            <AppGlyph app={e.app} size="sm" />
            <p className="min-w-0 flex-1 truncate text-[13.5px]">{describe(e)}</p>
            <span className="shrink-0 text-[11px] text-faint" title={e.source}>{when(e.ts)}</span>
          </motion.li>
        ))}
      </AnimatePresence>
    </ul>
  );
}
