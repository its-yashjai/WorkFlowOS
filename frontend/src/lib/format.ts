const d = (ts: string) => new Date(ts);
export function timeAgo(ts?: string | null) {
  if (!ts) return "";
  const s = (Date.now() - d(ts).getTime()) / 1000;
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  if (s < 86400 * 7) return `${Math.round(s / 86400)}d ago`;
  return d(ts).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}
export const clock = (ts: string) => d(ts).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
/** Time today, weekday + time otherwise. */
export const when = (ts: string) => (d(ts).toDateString() === new Date().toDateString() ? clock(ts) : dayTime(ts));
export const dayTime = (ts: string) => d(ts).toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });
export function dur(sec?: number) {
  if (!sec || sec < 1) return "0s";
  if (sec < 60) return `${Math.round(sec)}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${Math.round(sec % 60)}s`.replace(/ 0s$/, "");
  return `${Math.floor(sec / 3600)}h ${Math.round((sec % 3600) / 60)}m`;
}
export const initials = (n: string) => n.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();

/** Human sentence for an observed event. */
export function describe(e: { app: string; action: string; target: string; data: Record<string, unknown> }) {
  const v = (k: string) => String(e.data?.[k] ?? "");
  switch (`${e.app}.${e.action}`) {
    case "mail.open_email": return `Opened email "${v("subject")}" from ${v("from_name")}`;
    case "mail.download_attachment": return `Downloaded ${v("filename")}`;
    case "files.file_saved": return `Saved ${v("filename")} to ${v("folder") || "Downloads"}`;
    case "crm.search": return `Searched the CRM for "${v("query")}"`;
    case "crm.open_record": return `Opened ${v("name")} (${v("company")}) in the CRM`;
    case "crm.update_record": return `Updated ${e.target}'s record`;
    case "chat.open_channel": return `Opened ${v("channel")}`;
    case "chat.post_message": return `Posted in ${v("channel")}: "${v("text").slice(0, 60)}"`;
    case "desktop.app_focus": return `Switched to ${v("title") || v("process")}`;
    case "web.navigate": return `Visited ${v("domain")}${v("title") ? ` (${v("title")})` : ""}`;
    case "web.click": return `Clicked "${v("text")}" on ${v("domain")}`;
    case "web.submit": return `Submitted a form on ${v("domain")}`;
    default: return `${e.app}: ${e.action} ${e.target}`.trim();
  }
}
