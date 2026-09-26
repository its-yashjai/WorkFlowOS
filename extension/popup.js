const $ = (id) => document.getElementById(id);
async function render() {
  const c = await chrome.storage.local.get({ server: "http://localhost:8765", enabled: true, sent: 0, lastError: "", serverObserving: true });
  $("t").classList.toggle("on", c.enabled);
  $("s").value = c.server;
  $("status").innerHTML = c.lastError ? `<span class="bad">${c.lastError}</span>`
    : !c.serverObserving ? `<span class="muted">Paused in WorkFlowOS settings</span>`
    : `<span class="ok">Connected</span> · ${c.sent} events sent`;
}
$("t").onclick = async () => { const { enabled = true } = await chrome.storage.local.get("enabled"); await chrome.storage.local.set({ enabled: !enabled }); render(); };
$("s").onchange = async () => { await chrome.storage.local.set({ server: $("s").value.replace(/\/$/, "") }); render(); };
$("open").onclick = async (e) => { e.preventDefault(); const { server = "http://localhost:8765" } = await chrome.storage.local.get("server"); chrome.tabs.create({ url: server }); };
render();
