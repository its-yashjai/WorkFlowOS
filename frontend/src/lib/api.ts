import type { AppState, ChatMsg, Customer, Email, Run, WfEvent, Workflow, AskResult } from "./types";

/** Pages opened by the automation engine carry ?actor=automation so their clicks are not "observed". */
export const actorHeader = (): Record<string, string> =>
  new URLSearchParams(location.search).get("actor") === "automation" ? { "X-Actor": "automation" } : {};

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...actorHeader(), ...init?.headers } });
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try { const j = await res.json(); if (typeof j.detail === "string") msg = j.detail; } catch { /* not json */ }
    throw new Error(msg);
  }
  return res.json();
}
const body = (method: string, b?: unknown): RequestInit => ({ method, body: b === undefined ? undefined : JSON.stringify(b) });

export const api = {
  state: () => req<AppState>("/api/state"),
  settings: (s: Record<string, unknown>) => req<AppState>("/api/settings", body("PUT", s)),
  events: (limit = 60) => req<WfEvent[]>(`/api/events?limit=${limit}`),
  discover: () => req<Workflow[]>("/api/discover", body("POST")),
  workflows: () => req<Workflow[]>("/api/workflows"),
  workflow: (id: number) => req<{ workflow: Workflow; runs: Run[] }>(`/api/workflows/${id}`),
  patchWorkflow: (id: number, b: Partial<{ status: string; spec: unknown; name: string; mode: "preview" | "auto"; said: string }>) => req<Workflow>(`/api/workflows/${id}`, body("PATCH", b)),
  editSteps: (id: number, b: { op: "add" | "delete"; step_id?: string; after?: string | null; kind?: string; params?: Record<string, string> }) =>
    req<{ workflow: Workflow; message: string }>(`/api/workflows/${id}/steps`, body("POST", b)),
  answerProposal: (id: number, accept: boolean) => req<Workflow>(`/api/workflows/${id}/proposal`, body("POST", { accept })),
  runNow: (id: number, email_id?: number) => req<{ run_id: number }>(`/api/workflows/${id}/run`, body("POST", { email_id })),
  runs: (limit = 30) => req<Run[]>(`/api/runs?limit=${limit}`),
  run: (id: number) => req<Run>(`/api/runs/${id}`),
  resolve: (id: number, b: { customer_id?: number | null; create?: Record<string, string>; remember?: boolean; edits?: Record<string, Record<string, string>>; cancel?: boolean }) => req(`/api/runs/${id}/resolve`, body("POST", b)),
  ask: (id: number, text: string) => req<AskResult>(`/api/workflows/${id}/ask`, body("POST", { text })),
  undo: (id: number) => req(`/api/runs/${id}/undo`, body("POST")),
  testEmail: () => req<{ email_id: number; runs: number[] }>(`/api/demo/test-email`, body("POST")),
  sessions: () => req<{ start: string; end: string; events: WfEvent[]; tokens: string[]; apps: string[];
    matched: { id: number; name: string; idx: number[] }[] }[]>("/api/sessions"),
  reset: () => req("/api/demo/reset", body("POST")),
  connectGmail: (user: string, app_password: string) => req<{ ok: boolean; message: string }>("/api/connectors/gmail", body("POST", { user, app_password })),
  checkGmail: () => req<{ imported: number; runs: number[] }>("/api/connectors/gmail/check", body("POST")),
  connectSlack: (webhook: string) => req<{ ok: boolean; message: string }>("/api/connectors/slack", body("POST", { webhook })),
  // demo apps
  mail: () => req<Email[]>("/api/apps/mail"),
  openMail: (id: number) => req<Email>(`/api/apps/mail/${id}`),
  crm: (q = "") => req<Customer[]>(`/api/apps/crm?q=${encodeURIComponent(q)}`),
  customer: (id: number, quiet = false) => req<Customer>(`/api/apps/crm/${id}${quiet ? "?quiet=1" : ""}`),
  updateCustomer: (id: number, note: string, attachment: string) => req<Customer>(`/api/apps/crm/${id}`, body("PUT", { note, attachment })),
  chat: (channel: string) => req<{ channels: { channel: string; n: number; last: string | null }[]; messages: ChatMsg[] }>(`/api/apps/chat?channel=${encodeURIComponent(channel)}`),
  postChat: (channel: string, text: string) => req<{ id: number }>("/api/apps/chat", body("POST", { channel, text })),
};
