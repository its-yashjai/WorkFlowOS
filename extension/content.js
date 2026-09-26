// WorkFlowOS Observer: reports clicks on buttons/links and form submits.
// Only labels and field NAMES are sent, never what you typed.
(() => {
  const label = (el) => (el.getAttribute("aria-label") || el.innerText || el.value || el.title || "").trim().replace(/\s+/g, " ").slice(0, 40);
  const send = (m) => { try { chrome.runtime.sendMessage(m); } catch { /* extension reloaded */ } };
  document.addEventListener("click", (e) => {
    const el = e.target.closest("button, a, [role=button], input[type=submit], input[type=button]");
    if (!el) return;
    const text = label(el);
    if (!text || el.closest("input[type=password]")) return;
    send({ type: "click", text, kind: el.tagName === "A" ? "link" : "button" });
  }, true);
  document.addEventListener("submit", (e) => {
    const f = e.target;
    if (!(f instanceof HTMLFormElement) || f.querySelector("input[type=password]")) return;
    const fields = [...f.elements].map((x) => x.name || x.id).filter(Boolean).slice(0, 12);
    send({ type: "submit", form: f.getAttribute("aria-label") || f.name || f.id || f.getAttribute("action") || "form", fields });
  }, true);
})();
