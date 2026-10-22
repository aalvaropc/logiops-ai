export function showMessage(box, text, success = false) {
  box.textContent = text;
  box.className = text ? `message visible${success ? " success" : ""}` : "message";
  box.setAttribute("role", success || !text ? "status" : "alert");
  box.setAttribute("aria-live", success || !text ? "polite" : "assertive");
}

export function parkedPurchaseLine(parked, dollars) {
  return `A booking is waiting for “${parked.quote.plan_label}” on ${parked.incidentId} (${dollars(parked.quote.total_usd)}). `
    + "Say “resume” to hear the price again, or “no” to drop it. Nothing was charged.";
}

export function openHtml(html, { win = globalThis.window, urls = globalThis.URL, later = globalThis.setTimeout } = {}) {
  const url = urls.createObjectURL(new Blob([html], { type: "text/html" }));
  win.open(url, "_blank");
  later(() => urls.revokeObjectURL(url), 60000);
}

export async function loadAuthInto({ api, state, keepSession, renderAccount }) {
  const auth = await api.loadAuth();
  if (auth.unavailable) throw new Error("The sign-in settings could not be read.");
  state.auth = auth;
  if (!auth.enabled) keepSession(null);
  renderAccount();
}

export function createFocusKeeper({ doc = globalThis.document, fallback = () => null, defer = (work) => work() } = {}) {
  let kept = null;
  let handed = false;
  const usable = (node) => Boolean(node?.isConnected && !node.disabled && !node.closest?.("[hidden], [inert]"));

  return {
    remember(node = doc.activeElement) { kept = node; handed = false; },
    handTo(node) { kept = node; handed = true; },
    restore() {
      const before = kept;
      const forced = handed;
      kept = null;
      handed = false;
      if (!before) return;
      defer(() => {
        const active = doc.activeElement;
        if (!forced && active && active !== doc.body && usable(active)) return;
        const target = usable(before) ? before : fallback(before);
        if (usable(target)) target.focus({ preventScroll: true });
      });
    },
  };
}
