import { AnimatePresence, motion } from "framer-motion";
import { Bot, Eye } from "lucide-react";
import { ReactNode, useEffect, useRef, useState } from "react";
import { useApp } from "../lib/store";
import AppGlyph, { APPS } from "../components/AppGlyph";

/** Chrome around each demo app. The "Observed" pill flashes whenever WorkFlowOS records one of your actions. */
export default function AppFrame({ app, children, right }: { app: "mail" | "crm" | "chat"; children: ReactNode; right?: ReactNode }) {
  const { version, state } = useApp();
  const automation = new URLSearchParams(location.search).get("actor") === "automation";
  const [flash, setFlash] = useState(0);
  const first = useRef(true);
  useEffect(() => { if (first.current) { first.current = false; return; } setFlash((f) => f + 1); }, [version.activity]);
  const observing = state?.settings.observing === "1";
  return (
    <div className="flex h-[100dvh] flex-col lg:h-screen">
      <header className="flex items-center gap-3 border-b hairline px-4 py-3 sm:px-6">
        <AppGlyph app={app} />
        <h1 className="font-display text-xl font-bold tracking-tight">{APPS[app].label}</h1>
        <div className="ml-auto flex items-center gap-2">
          {right}
          {automation ? (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-flow/15 px-3 py-1 text-xs font-medium text-flow"><Bot className="h-3.5 w-3.5" />Automation session</span>
          ) : (
            <span className="relative inline-flex items-center gap-1.5 rounded-full bg-hand/12 px-3 py-1 text-xs font-medium text-hand" title="Your actions here are observed by WorkFlowOS">
              <Eye className="h-3.5 w-3.5" />{observing ? "Observed" : "Not observed"}
              <AnimatePresence>
                {flash > 0 && (
                  <motion.span key={flash} className="absolute inset-0 rounded-full border-2 border-hand" initial={{ opacity: 1, scale: 1 }} animate={{ opacity: 0, scale: 1.6 }} transition={{ duration: 0.9 }} />
                )}
              </AnimatePresence>
            </span>
          )}
        </div>
      </header>
      <div className="min-h-0 flex-1">{children}</div>
    </div>
  );
}
