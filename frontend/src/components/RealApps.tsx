import { Hash, Mail, RefreshCw } from "lucide-react";
import { useState } from "react";
import clsx from "clsx";
import { api } from "../lib/api";
import { timeAgo } from "../lib/format";
import { useApp } from "../lib/store";
import { Button } from "./ui";

const input = "h-10 w-full rounded-xl border border-white/12 bg-white/[0.04] px-3 text-sm outline-none placeholder:text-faint focus:border-volt";

/** Connect the real Gmail inbox (in) and a real Slack channel (out). */
export default function RealApps() {
  const { state, refresh, toast } = useApp();
  const c = state?.connectors;
  const [user, setUser] = useState(c?.gmail.user || "");
  const [pw, setPw] = useState("");
  const [hook, setHook] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const call = async (k: string, fn: () => Promise<{ ok?: boolean; message?: string; imported?: number }>) => {
    setBusy(k);
    try {
      const r = await fn();
      if (r.message) toast(r.message, r.ok ? "good" : "bad");
      else if (r.imported != null) toast(r.imported ? `${r.imported} new email${r.imported > 1 ? "s" : ""} from Gmail` : "No new Gmail emails with attachments", "good");
      await refresh();
    } catch (e) { toast((e as Error).message, "bad"); } finally { setBusy(null); }
  };
  if (!c) return null;
  return (
    <section className="space-y-4 rounded-2xl border hairline bg-white/[0.03] p-4">
      <div>
        <h3 className="font-display text-base font-semibold">Real apps</h3>
        <p className="text-sm text-mist">Optional. Without them, the built-in Mailbox and Huddle are used.</p>
      </div>

      <div className="space-y-2">
        <p className="flex items-center justify-between gap-2 text-sm font-medium">
          <span className="flex items-center gap-2"><Mail className="h-4 w-4 text-[#FF8A84]" />Gmail (new emails come in)</span>
          <Dot on={c.gmail.connected} error={c.gmail.error} />
        </p>
        {c.gmail.connected ? (
          <>
            <p className="text-xs text-mist">{c.gmail.user} · checks every 15 s · only new emails with an attachment · {c.gmail.imported} imported
              {c.gmail.checked ? ` · last check ${timeAgo(c.gmail.checked)}` : ""}</p>
            {c.gmail.error && <p className="text-xs text-bad">{c.gmail.error}</p>}
            <div className="flex gap-2">
              <Button size="sm" busy={busy === "check"} icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={() => call("check", api.checkGmail)}>Check now</Button>
              <Button size="sm" variant="quiet" busy={busy === "gx"} onClick={() => call("gx", () => api.connectGmail("", ""))}>Disconnect</Button>
            </div>
          </>
        ) : (
          <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); call("g", () => api.connectGmail(user, pw)); }}>
            <input className={input} value={user} onChange={(e) => setUser(e.target.value)} placeholder="you@gmail.com" type="email" required aria-label="Gmail address" />
            <input className={input} value={pw} onChange={(e) => setPw(e.target.value)} placeholder="16-letter App Password" type="password" required aria-label="Gmail App Password" />
            <Button size="sm" variant="primary" busy={busy === "g"}>Connect Gmail</Button>
            <p className="text-xs text-faint">Google Account → Security → 2-Step Verification on → App passwords → create one. WorkFlowOS reads the inbox read-only.</p>
          </form>
        )}
      </div>

      <div className="space-y-2">
        <p className="flex items-center justify-between gap-2 text-sm font-medium">
          <span className="flex items-center gap-2"><Hash className="h-4 w-4 text-volt" />Slack (team notifications go out)</span>
          <Dot on={c.slack.connected} error={c.slack.error} />
        </p>
        {c.slack.connected ? (
          <>
            <p className="text-xs text-mist">Webhook connected · {c.slack.sent} messages sent</p>
            {c.slack.error && <p className="text-xs text-bad">{c.slack.error}</p>}
            <Button size="sm" variant="quiet" busy={busy === "sx"} onClick={() => call("sx", () => api.connectSlack(""))}>Disconnect</Button>
          </>
        ) : (
          <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); call("s", () => api.connectSlack(hook)); }}>
            <input className={input} value={hook} onChange={(e) => setHook(e.target.value)} placeholder="https://hooks.slack.com/services/…" required aria-label="Slack webhook URL" />
            <Button size="sm" variant="primary" busy={busy === "s"}>Connect Slack</Button>
            <p className="text-xs text-faint">api.slack.com/apps → Create app → Incoming Webhooks → on → Add to a channel → copy the URL.</p>
          </form>
        )}
      </div>
    </section>
  );
}

function Dot({ on, error }: { on: boolean; error?: string }) {
  return (
    <span className={clsx("flex items-center gap-1.5 text-xs font-normal", on ? (error ? "text-hand" : "text-ok") : "text-faint")}>
      <span className={clsx("h-2 w-2 rounded-full", on ? (error ? "bg-hand" : "bg-ok") : "bg-faint")} />{on ? (error ? "Problem" : "Connected") : "Not connected"}
    </span>
  );
}
