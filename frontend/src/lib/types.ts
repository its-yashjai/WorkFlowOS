export type AppKey = "mail" | "crm" | "chat" | "files" | "desktop" | "web";

export interface WfEvent { id: number; ts: string; source: string; app: AppKey; action: string; target: string; data: Record<string, unknown> }

export interface Step {
  id: string; app: AppKey; action: string; label: string; params?: Record<string, string>; out?: string[];
  tiers?: string[]; learned_confidence?: number;
  when?: { var: string; any: string[]; show: string[]; negate?: boolean; label: string };
}
export interface Spec {
  name: string; description: string;
  trigger: { type: string; app?: string; has_attachment?: boolean; label: string };
  steps: Step[]; conditions: { after: string; if: string; then: string; label: string }[]; variables: string[];
  evidence: { times_seen: number; avg_manual_seconds: number; app_switches: number; apps: string[];
    examples: { customer?: string; subject?: string; message?: string; note?: string; when?: string; seconds?: number }[] };
}
export interface Workflow {
  id: number; name: string; intent: string; status: "suggested" | "active" | "paused" | "dismissed"; spec: Spec;
  pattern: { steps: string[]; support: number; avg_seconds: number; switches: number; apps: string[]; score: number; last_seen: string };
  learned: { aliases?: Record<string, number>; log?: string[]; mode?: "preview" | "auto"; suggest_auto?: boolean; ui?: Record<string, unknown> };
  stats: { runs?: number; succeeded?: number; time_saved_sec?: number; last_run?: string; clean_streak?: number };
  created_at: string; updated_at: string;
}
export interface RunStep {
  id: string; label: string; app: AppKey; action: string; status: "pending" | "running" | "done" | "failed" | "waiting" | "skipped";
  tier: string | null; tried: { tier: string; ok: boolean; detail: string }[]; detail: string; ms: number;
  healed?: Healed[]; undo?: Record<string, unknown>; undone?: boolean;
}
export interface Run {
  id: number; workflow_id: number; workflow_name?: string; status: "running" | "done" | "failed" | "needs_you" | "undone" | "cancelled";
  trigger: { type: string; email_id?: number; subject?: string; from?: string }; vars: Record<string, unknown>;
  steps: RunStep[]; note: { reason?: string; step?: number; suggested?: number | null; suggested_name?: string | null; email?: string; name?: string; kind?: string; label?: string; url?: string | null; hint?: string; changes?: Change[] };
  started_at: string; finished_at: string | null;
}
export interface AgentInfo { name: string; source: string; last_seen: string; online: boolean; info: Record<string, unknown> }
export interface AppState {
  settings: Record<string, string>; llm: boolean; ai?: AiStatus; groq_key_set?: boolean;
  connectors?: { gmail: { connected: boolean; user: string; error: string; checked: string | null; imported: number }; slack: { connected: boolean; error: string; sent: number } }; agents: AgentInfo[];
  counts: { events: number; runs: number; active: number; suggested: number; time_saved_sec: number };
}
export interface Email { id: number; sender_name: string; sender_email: string; subject: string; body: string; attachment: string; received_at: string; read: number; handled_by: number | null; source?: string }
export interface Customer { id: number; name: string; email: string; company: string; tier: string; notes: { text: string; ts: string; by: string; attachment?: string }[]; files: string[]; updated_at: string }
export interface ChatMsg { id: number; channel: string; author: string; text: string; ts: string; bot: number }
export interface Healed { target: string; before: string; after: string; confidence: number }
export interface Change {
  step: string; app: AppKey; label: string; where: string; last_note?: string | null;
  fields: { key: string; label: string; value: string; readonly?: boolean }[];
}
export interface AiStatus { engine: "ollama" | "groq" | "rules"; model: string | null; local: boolean; label: string }
export interface AskResult {
  ops: Record<string, unknown>[]; changes: { kind: "add" | "change" | "remove"; text: string }[]; spec: Spec;
  engine: "ollama" | "groq" | "rules"; model: string | null; local: boolean; ms: number; note: string; understood: boolean;
}
