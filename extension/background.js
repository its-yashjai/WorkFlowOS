// WorkFlowOS Observer: background service worker.
const DEFAULTS = { server: "http://localhost:8765", enabled: true, sent: 0 };
const SENSITIVE = /(bank|paypal|netbanking|login|signin|accounts\.google|password|auth|checkout|payment)/i;
// Chrome stops an idle extension service worker after about 30 seconds and its variables are lost,
// so the events waiting to be sent live in chrome.storage, not in a variable.
const MAX_QUEUE = 500;
let flushTimer = null;
let chain = Promise.resolve();  // storage reads/writes run one after another, so no event is overwritten
const locked = (fn) => (chain = chain.then(fn, fn));

const cfg = () => chrome.storage.local.get(DEFAULTS);

function skip(url, server) {
  try {
    const u = new URL(url);
    if (!/^https?:$/.test(u.protocol)) return true;
    if (server && u.origin === new URL(server).origin) return true; // WorkFlowOS observes its own apps
    return SENSITIVE.test(u.hostname + u.pathname);
  } catch { return true; }
}

async function emit(action, url, data) {
  const c = await cfg();
  if (!c.enabled || skip(url, c.server)) return;
  const u = new URL(url);
  const ts = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 19);
  const ev = { app: "web", action, target: u.hostname, source: "extension", ts,
    data: { domain: u.host.replace(/^www\./, ""), origin: u.origin, path: u.pathname.slice(0, 120), ...data } };
  await locked(async () => {
    const { queue = [] } = await chrome.storage.local.get({ queue: [] });
    queue.push(ev);
    await chrome.storage.local.set({ queue: queue.slice(-MAX_QUEUE) });
  });
  clearTimeout(flushTimer);
  flushTimer = setTimeout(flush, 1500);  // if the worker is stopped before this fires, the alarm below sends it
}

function flush() {
  return locked(async () => {
    const { queue = [] } = await chrome.storage.local.get({ queue: [] });
    if (!queue.length) return;
    const c = await cfg();
    try {
      const r = await fetch(c.server + "/api/events", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(queue) });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const j = await r.json();
      await chrome.storage.local.set({ queue: [], sent: (c.sent || 0) + (j.stored || 0), lastError: "" });  // only now is it safe to forget them
    } catch (e) {
      await chrome.storage.local.set({ lastError: "Can't reach " + c.server });  // keep the events and try again later
    }
  });
}

async function heartbeat() {
  const c = await cfg();
  try {
    const r = await fetch(c.server + "/api/agents/heartbeat", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "chrome-extension", source: "extension", info: { browser: navigator.userAgent.includes("Edg/") ? "Edge" : "Chrome", sent: c.sent } }) });
    const j = await r.json();
    await chrome.storage.local.set({ serverObserving: !!j.observing, lastError: "" });
  } catch { await chrome.storage.local.set({ lastError: "Can't reach " + c.server }); }
}

// page navigations (one per finished load)
chrome.tabs.onUpdated.addListener((tabId, info, tab) => {
  if (info.status === "complete" && tab.url && !tab.incognito) emit("navigate", tab.url, { title: (tab.title || "").slice(0, 120) });
});

// clicks and form submits from content.js
chrome.runtime.onMessage.addListener((msg, sender) => {
  if (!sender.tab || sender.tab.incognito || !sender.tab.url) return;
  if (msg.type === "click") emit("click", sender.tab.url, { text: msg.text, kind: msg.kind });
  if (msg.type === "submit") emit("form_submit", sender.tab.url, { form: msg.form, fields: msg.fields });
});

// finished downloads
chrome.downloads.onChanged.addListener(async (d) => {
  if (d.state?.current !== "complete") return;
  const [item] = await chrome.downloads.search({ id: d.id });
  if (item) emit("download", item.url || item.referrer || "https://unknown/", { filename: item.filename.split(/[\\/]/).pop() });
});

chrome.alarms.create("hb", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "hb") { heartbeat(); flush(); } });
chrome.runtime.onInstalled.addListener(heartbeat);
chrome.runtime.onStartup.addListener(heartbeat);
