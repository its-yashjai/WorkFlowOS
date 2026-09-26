import { BookUser, Folder, Globe, Mail, MessagesSquare, Monitor, Zap } from "lucide-react";
import clsx from "clsx";

export const APPS: Record<string, { label: string; icon: typeof Mail; cls: string }> = {
  mail: { label: "Mailbox", icon: Mail, cls: "bg-[#E8544E]/15 text-[#FF8A84]" },
  crm: { label: "Ledger CRM", icon: BookUser, cls: "bg-volt/15 text-volt" },
  chat: { label: "Huddle", icon: MessagesSquare, cls: "bg-[#B57CFF]/15 text-[#C9A2FF]" },
  files: { label: "Files", icon: Folder, cls: "bg-hand/15 text-hand" },
  desktop: { label: "Desktop", icon: Monitor, cls: "bg-white/10 text-mist" },
  web: { label: "Web", icon: Globe, cls: "bg-flow/15 text-flow" },
  trigger: { label: "Trigger", icon: Zap, cls: "bg-hand/15 text-hand" },
};

export default function AppGlyph({ app, size = "md" }: { app: string; size?: "sm" | "md" | "lg" }) {
  const a = APPS[app] || APPS.desktop;
  const I = a.icon;
  return (
    <span className={clsx("grid shrink-0 place-items-center rounded-xl", a.cls,
      size === "sm" ? "h-7 w-7" : size === "lg" ? "h-12 w-12 rounded-2xl" : "h-9 w-9")} title={a.label}>
      <I className={size === "sm" ? "h-3.5 w-3.5" : size === "lg" ? "h-6 w-6" : "h-4 w-4"} />
    </span>
  );
}
