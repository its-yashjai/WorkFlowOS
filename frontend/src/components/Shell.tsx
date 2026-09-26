import { motion } from "framer-motion";
import { BookUser, Eye, EyeOff, Mail, MessagesSquare, Settings2, Workflow } from "lucide-react";
import { ReactNode, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import clsx from "clsx";
import { useApp } from "../lib/store";
import SettingsSheet from "./SettingsSheet";
import { spring } from "./ui";

export function Logo({ small }: { small?: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <img src="/icon.svg" alt="" className={small ? "h-8 w-8" : "h-8 w-8"} />
      {!small && <span className="font-display text-lg font-bold tracking-tight">WorkFlow<span className="text-flow">OS</span></span>}
    </div>
  );
}

const NAV = [
  { to: "/", label: "Workflows", icon: Workflow, match: (p: string) => p === "/" || p.startsWith("/workflow") || p.startsWith("/run") },
  { to: "/activity", label: "Observed", icon: Eye, match: (p: string) => p.startsWith("/activity") },
];
const APPS = [
  { to: "/apps/mail", label: "Mailbox", icon: Mail },
  { to: "/apps/crm", label: "Ledger", icon: BookUser },
  { to: "/apps/chat", label: "Huddle", icon: MessagesSquare },
];

export default function Shell({ children }: { children: ReactNode }) {
  const loc = useLocation();
  const { state } = useApp();
  const [settings, setSettings] = useState(false);
  const observing = state?.settings.observing === "1";
  const suggested = state?.counts.suggested ?? 0;
  const item = (to: string, label: string, Icon: typeof Eye, active: boolean, badge?: number, id = "rail") => (
    <NavLink key={to} to={to} className={clsx("relative flex w-16 flex-col items-center gap-1 rounded-2xl py-2.5 text-[11px] font-medium transition-colors",
      active ? "text-paper" : "text-faint hover:text-mist")}>
      {active && <motion.span layoutId={id} transition={spring} className="absolute inset-0 rounded-2xl bg-white/[0.08]" />}
      <Icon className="relative h-5 w-5" /><span className="relative">{label}</span>
      {!!badge && <span className="absolute right-2 top-1.5 grid h-4 min-w-4 place-items-center rounded-full bg-hand px-1 text-[10px] font-bold text-ink">{badge}</span>}
    </NavLink>
  );
  return (
    <div className="relative z-10 flex min-h-screen">
      <nav className="sticky top-0 hidden h-screen w-[84px] shrink-0 flex-col items-center gap-1.5 border-r hairline py-5 lg:flex" aria-label="Main">
        <NavLink to="/" className="mb-5" aria-label="WorkFlowOS home"><Logo small /></NavLink>
        {NAV.map((n) => item(n.to, n.label, n.icon, n.match(loc.pathname), n.to === "/" ? suggested : undefined))}
        <p className="mt-4 text-[10px] font-medium text-faint">Your apps</p>
        {APPS.map((n) => item(n.to, n.label, n.icon, loc.pathname.startsWith(n.to)))}
        <button onClick={() => setSettings(true)} className="mt-2 flex w-16 flex-col items-center gap-1 rounded-2xl py-2.5 text-[11px] font-medium text-faint hover:text-mist">
          <Settings2 className="h-5 w-5" />Settings
        </button>
        <div className="mt-auto flex flex-col items-center gap-1 text-[10px] text-faint" title={observing ? "WorkFlowOS is observing your work" : "Observation is paused"}>
          <motion.span animate={observing ? { boxShadow: ["0 0 0px #FFB547", "0 0 16px #FFB547", "0 0 0px #FFB547"] } : {}} transition={{ duration: 2.2, repeat: Infinity }}
            className={clsx("grid h-9 w-9 place-items-center rounded-full", observing ? "bg-hand/20 text-hand" : "bg-white/[0.06] text-faint")}>
            {observing ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
          </motion.span>
          {observing ? "Observing" : "Paused"}
        </div>
      </nav>

      <main className="min-w-0 flex-1 pb-tabbar">{children}</main>

      <nav className="panel fixed inset-x-3 bottom-3 z-40 flex items-center justify-around rounded-2xl px-1 py-1.5 lg:hidden" aria-label="Main">
        {[...NAV, ...APPS.map((a) => ({ ...a, match: (p: string) => p.startsWith(a.to) }))].map((n) => {
          const active = n.match(loc.pathname);
          return (
            <NavLink key={n.to} to={n.to} className={clsx("relative flex flex-1 flex-col items-center gap-0.5 rounded-xl py-1.5 text-[10.5px] font-medium", active ? "text-paper" : "text-faint")}>
              {active && <motion.span layoutId="tabbar" transition={spring} className="absolute inset-0 rounded-xl bg-white/[0.08]" />}
              <n.icon className="relative h-5 w-5" /><span className="relative">{n.label}</span>
            </NavLink>
          );
        })}
        <button onClick={() => setSettings(true)} className="flex flex-1 flex-col items-center gap-0.5 py-1.5 text-[10.5px] font-medium text-faint" aria-label="Settings">
          <Settings2 className="h-5 w-5" />More
        </button>
      </nav>
      <SettingsSheet open={settings} onClose={() => setSettings(false)} />
    </div>
  );
}
