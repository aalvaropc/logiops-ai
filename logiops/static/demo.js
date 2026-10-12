"use strict";

import { createApi, createStorage, explainError as explain } from "./app/api.js";
import { createMcpClient } from "./app/mcp.js";

const $ = (id) => document.getElementById(id);
const DEFAULT_INCIDENT = "SHIP-421";
const hashIncident = () => decodeURIComponent(location.hash.slice(1)).trim().toUpperCase() || DEFAULT_INCIDENT;
const state = {
  token: "", snapshot: null, selectedPlanId: null, busy: false, conversation: [], speaking: false, app: null,
  awaitingExecute: false, pendingApproval: null, incidentId: hashIncident(), inbox: [], conversations: {}, selections: {}, stockFor: null,
  briefingPick: null, prefsShown: undefined, cardTheme: "dark", pendingPurchase: null, alerts: [],
  voice: { engine: "browser", voice: null, fillers: [] }, speechTurn: 0, auth: { enabled: false }, session: null,
  memoryIncident: null,
};
const CAPABILITIES_TEXT = "I'm LogiOps, your operations desk for late or held shipments. I can:\n"
  + "- brief your queue: say “any delays today?”;\n"
  + "- investigate an incident and compare its plans: “what's happening with SHIP-433?”;\n"
  + "- answer follow-ups from that investigation: “why not the cheaper one?”;\n"
  + "- remember preferences for every incident: “remember my spend cap is $250”;\n"
  + "- approve a plan after reading it back, then execute it: “approve the recommended plan”, “yes”, “execute it”;\n"
  + "- book and pay a plan's carriers after reading back the price with IGV, with a receipt: “book it”, “yes”;\n"
  + "- start over at any time: “start over”.\n"
  + "Every answer is checked against the incident's data, and only you can approve.";
const CAPABILITIES_SPOKEN = "I can brief your queue, investigate an incident and compare plans, remember your preferences, approve and execute a plan, and book and pay its carriers after reading the price back to you. Try: any delays today?";
const incidentPath = (suffix = "") => `/incidents/${encodeURIComponent(state.incidentId)}${suffix}`;
const device = (method, ...args) => {
  const api = window.LogiOpsDevice;
  if (api && typeof api[method] === "function") api[method](...args);
};
const MCP_APP = {
  uriPrefix: "ui://logiops/resolution-options", mime: "text/html;profile=mcp-app", protocol: "2026-01-26",
  proxyPath: "/mcp-app/sandbox.html",
};
const SANDBOX_ORIGIN = (() => {
  const value = document.querySelector('meta[name="logiops-sandbox-origin"]')?.content || "";
  try {
    const url = new URL(value);
    return /^https?:$/.test(url.protocol) && url.origin !== location.origin ? url.origin : null;
  } catch (_) { return null; }
})();
const app = { generation: 0, resource: null, nextId: 1 };
const eventLabels = {
  scenario_reset: "Synthetic incident reset",
  incident_investigated: "MCP investigation completed",
  agent_investigation_completed: "Agent assessment recorded",
  plan_approved: "Plan approved by operator",
  plan_executed: "Fulfillment plan executed",
  notifications_simulated: "Notifications simulated",
  execution_verified: "All units accounted for",
  inventory_changed: "Local inventory changed",
  schema_migrated: "Data rebuilt for a new version",
};
const planKeywords = [
  [["express-transfer"], /\btransfer\b/],
  [["priority-air-ground"], /\b(air|fly|flight)\b.*\bground\b|\bground\b.*\b(air|fly|flight)\b/],
  [["priority-air"], /\b(air|fly|flight)\b/],
  [["split-expedite"], /\b(split|stock)\b.*\bexpedit|\bexpedit\w*\b.*\b(split|stock)\b/],
  [["expedite", "split-expedite"], /\bexpedit\w*\b|\bbroker\b/],
  [["first-come"], /\b(first[- ]come|as placed|school first)\b/],
  [["priority-first"], /\b(hospital first|priority first)\b/],
  [["split-express", "split-expedite", "split-wait"], /\bsplit\b/],
  [["split-express"], /\bexpress\b/],
  [["local-stock"], /\b(local|warehouse)\b/],
  [["reroute"], /\b(reroute|re-route|economy|rebook)\b/],
  [["wait"], /\bwait\b/],
];

function message(text, success = false) {
  const box = $("message");
  box.textContent = text;
  box.className = text ? `message visible${success ? " success" : ""}` : "message";
  box.setAttribute("role", success || !text ? "status" : "alert");
  box.setAttribute("aria-live", success || !text ? "polite" : "assertive");
}

function setBusy(busy) {
  state.busy = busy;
  renderControls();
}

function explainError(status, detail) {
  return explain(status, detail, { authEnabled: state.auth.enabled, signedIn: Boolean(state.session), hasToken: Boolean(state.token) });
}

const PURCHASE_KEY = "logiops-pending-purchase";
function storedPurchase() {
  try {
    const value = JSON.parse(sessionStorage.getItem(PURCHASE_KEY) || "null");
    return value && value.quote && Date.parse(value.quote.expires_at) > Date.now() ? value : null;
  } catch (_) { return null; }
}
function keepPurchase(purchase) {
  state.pendingPurchase = purchase;
  try {
    if (purchase) sessionStorage.setItem(PURCHASE_KEY, JSON.stringify(purchase)); else sessionStorage.removeItem(PURCHASE_KEY);
  } catch (_) { }
}
function forgetPurchase() {
  keepPurchase(null);
}

const api = createApi({
  storage: createStorage(), origin: location.origin,
  credentials: () => ({ token: state.token, session: state.session, auth: state.auth }),
  onSession: (session) => {
    state.session = session;
    state.token = session ? session.access : api.storedToken();
    if (session) $("approver").value = session.username;
    renderAccount();
  },
  onAgentCall: (phase) => {
    if (phase === "request") {
      device("voice", "request");
      startFiller();
      return;
    }
    clearTimeout(state.fillerTimer);
    if (phase === "error") device("voice", "error");
  },
});
const { request, storedToken, storeToken, readSession, keepSession, signOut, randomText } = api;
function renderAccount() {
  const box = $("account");
  box.hidden = !state.auth.enabled;
  box.classList.toggle("signed-in", Boolean(state.session));
  $("account-status").textContent = state.session ? `Signed in as ${state.session.username}` : "Guest · read only";
  $("link-account").hidden = Boolean(state.session);
  $("sign-out").hidden = !state.session;
}
async function loadAuth() {
  state.auth = await api.loadAuth();
  if (!state.auth.enabled) keepSession(null);
  renderAccount();
}
async function linkAccount() {
  if (!state.auth.enabled) {
    say("assistant", "Sign-in isn't set up on this server, so the demo already acts as the operator.");
    return;
  }
  const url = await api.beginSignIn({ hash: location.hash });
  if (!url) {
    say("assistant", "This browser blocks session storage, so I can't sign you in here.");
    return;
  }
  location.assign(url);
}
async function finishSignIn() {
  const outcome = await api.finishSignIn({ search: location.search, hash: location.hash });
  if (!outcome) return;
  history.replaceState(null, "", outcome.path);
  state.signInNote = outcome.note;
}

const mcpClient = createMcpClient({ getToken: () => state.token });
const mcpRequest = (method, params) => mcpClient.request(method, params);

function hostContext() {
  const slot = $("mcp-app-slot");
  const width = Math.round(slot?.clientWidth || window.innerWidth);
  return {
    theme: state.cardTheme, displayMode: "inline", availableDisplayModes: ["inline"],
    containerDimensions: { width, maxHeight: 640 }, locale: navigator.language || "en-US", timeZone: "America/Lima",
    platform: "web", deviceClass: width < 480 ? "compact" : "regular",
    deviceCapabilities: { touch: matchMedia("(pointer: coarse)").matches, hover: matchMedia("(hover: hover)").matches },
    safeAreaInsets: { top: 0, right: 0, bottom: 0, left: 0 },
  };
}

function sendHostContext() {
  const frame = $("mcp-app-frame");
  if (!state.app?.ready || !frame) return;
  frame.contentWindow.postMessage({ jsonrpc: "2.0", method: "ui/notifications/host-context-changed", params: hostContext() }, SANDBOX_ORIGIN);
}

function loadAppResource() {
  app.resource ??= (async () => {
    const listed = await mcpRequest("tools/list", {});
    const tool = listed.tools.find((item) => item.name === "investigate_incident");
    const uri = tool?._meta?.ui?.resourceUri ?? tool?._meta?.["ui/resourceUri"];
    if (typeof uri !== "string" || !uri.startsWith(MCP_APP.uriPrefix)) return null;
    const read = await mcpRequest("resources/read", { uri });
    const content = read.contents?.[0];
    if (!content || content.mimeType !== MCP_APP.mime || typeof content.text !== "string") return null;
    const ui = content._meta?.ui || {};
    return { uri, html: content.text, csp: ui.csp || {}, prefersBorder: ui.prefersBorder !== false, invoked: tool._meta.ui?.invoked || "" };
  })().catch((error) => { app.resource = null; throw error; });
  return app.resource;
}

async function showMcpApp(run) {
  const step = run.tool_trace?.find((item) => item.tool === "investigate_incident" && !item.is_error);
  if (!step) return;
  if (!SANDBOX_ORIGIN) {
    console.info("MCP App not shown: no sandbox origin separate from this page is configured.");
    showMcpAppNote("The interactive card needs a second origin for its sandbox, and none is available on this address. "
      + "Open the demo on 127.0.0.1 or localhost, or on the deployed hostname. The plans are listed below.");
    return;
  }
  const generation = ++app.generation;
  const resource = await loadAppResource();
  if (!resource || generation !== app.generation || !state.snapshot
      || String(step.input?.shipment_id || "").trim().toUpperCase() !== state.incidentId
      || step.output.source_version !== visibleVersion(state.snapshot)) return;
  await teardownMcpApp("replaced", { invalidate: false });
  if (generation !== app.generation) return;
  state.app = {
    incidentId: state.incidentId,
    version: step.output.source_version,
    input: step.input,
    result: {
      content: [{ type: "text", text: JSON.stringify(step.output) }], structuredContent: step.output,
      _meta: { "logiops/recommended_plan_id": recommendedPlan(state.snapshot)?.id || null },
    },
    resource,
    ready: false,
  };
  const frame = document.createElement("iframe");
  frame.id = "mcp-app-frame";
  frame.title = "Resolution options (MCP App)";
  frame.setAttribute("sandbox", "allow-scripts allow-same-origin");
  frame.setAttribute("referrerpolicy", "no-referrer");
  frame.src = `${SANDBOX_ORIGIN}${MCP_APP.proxyPath}?host=${encodeURIComponent(location.origin)}`;
  $("mcp-app-slot").replaceChildren(frame);
  $("mcp-app-uri").textContent = resource.uri;
  $("mcp-app-status").textContent = resource.invoked ? `· ${resource.invoked}` : "";
  $("mcp-app").classList.toggle("borderless", !resource.prefersBorder);
  $("mcp-app").hidden = false;
}

function teardownMcpApp(reason, { invalidate = true } = {}) {
  const current = state.app;
  const frame = $("mcp-app-frame");
  state.app = null;
  if (invalidate) app.generation += 1;
  $("mcp-app").hidden = true;
  if (!frame) return Promise.resolve();
  return new Promise((resolve) => {
    let finished = false;
    const id = `teardown-${app.nextId++}`;
    const finish = () => {
      if (finished) return;
      finished = true;
      window.removeEventListener("message", onReply);
      frame.remove();
      resolve();
    };
    const onReply = (event) => {
      if (event.source === frame.contentWindow && event.origin === SANDBOX_ORIGIN && event.data?.id === id) finish();
    };
    if (!current?.ready) return finish();
    window.addEventListener("message", onReply);
    frame.contentWindow.postMessage({ jsonrpc: "2.0", id, method: "ui/resource-teardown", params: { reason } }, SANDBOX_ORIGIN);
    setTimeout(finish, 500);
  });
}

function hideMcpApp(reason = "hidden") {
  teardownMcpApp(reason);
}

function showMcpAppNote(text) {
  const frame = $("mcp-app-frame");
  if (frame) frame.remove();
  const note = document.createElement("p");
  note.className = "mcp-app-note";
  note.textContent = text;
  $("mcp-app-slot").replaceChildren(note);
  $("mcp-app-status").textContent = "";
  $("mcp-app").hidden = false;
}

$("mcp-app-theme").addEventListener("click", () => {
  state.cardTheme = state.cardTheme === "dark" ? "light" : "dark";
  $("mcp-app-theme").setAttribute("aria-pressed", String(state.cardTheme === "light"));
  sendHostContext();
});
let contextTimer = 0;
window.addEventListener("resize", () => {
  clearTimeout(contextTimer);
  contextTimer = setTimeout(sendHostContext, 200);
});

function selectFromApp(params) {
  const text = params?.content?.type === "text" ? String(params.content.text) : "";
  const match = text.match(/^Select plan (\S+)$/);
  if (!match || !state.snapshot || state.busy) return false;
  const plan = visiblePlans(state.snapshot).find((item) => item.id === match[1]);
  if (!plan || visibleApproval(state.snapshot) || state.snapshot.executions.length) return false;
  state.selectedPlanId = plan.id;
  renderPlans(state.snapshot);
  renderControls();
  message(`“${plan.label}” selected from the MCP App. Approve it with the operator button below.`, true);
  return true;
}

window.addEventListener("message", (event) => {
  const frame = $("mcp-app-frame");
  if (!state.app || !frame || event.source !== frame.contentWindow || event.origin !== SANDBOX_ORIGIN) return;
  const msg = event.data;
  if (!msg || msg.jsonrpc !== "2.0" || typeof msg.method !== "string") return;
  const send = (payload) => frame.contentWindow.postMessage({ jsonrpc: "2.0", ...payload }, SANDBOX_ORIGIN);
  const reply = (payload) => { if (msg.id !== undefined) send({ id: msg.id, ...payload }); };
  if (msg.method === "ui/notifications/sandbox-proxy-ready") {
    send({ method: "ui/notifications/sandbox-resource-ready", params: { html: state.app.resource.html, csp: state.app.resource.csp } });
  } else if (msg.method === "logiops/sandbox-view-removed") {
    hideMcpApp("view navigated");
  } else if (msg.method === "ui/initialize") {
    reply({ result: {
      protocolVersion: MCP_APP.protocol,
      hostInfo: { name: "LogiOps Alexa+-style demo", version: "1.0.0" },
      hostCapabilities: {},
      hostContext: hostContext(),
    } });
  } else if (msg.method === "ui/notifications/initialized") {
    state.app.ready = true;
    send({ method: "ui/notifications/tool-input", params: { arguments: state.app.input } });
    send({ method: "ui/notifications/tool-result", params: state.app.result });
  } else if (msg.method === "ui/notifications/size-changed") {
    const height = Number(msg.params?.height);
    if (Number.isFinite(height)) frame.style.height = `${Math.min(Math.max(height, 80), 640)}px`;
  } else if (msg.method === "ui/message") {
    reply(selectFromApp(msg.params) ? { result: {} } : { error: { code: -32000, message: "Unknown or unavailable plan, or the operator panel is busy" } });
  } else {
    reply({ error: { code: -32601, message: "Method not supported by this host" } });
  }
});

function formatDate(iso) {
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "America/Lima" }).format(new Date(iso));
}

function visibleVersion(snapshot) {
  return snapshot.executions[0]?.source_version ?? snapshot.source_version;
}

function visibleApproval(snapshot) {
  return snapshot.approvals.find((approval) => approval.source_version === visibleVersion(snapshot));
}

function visiblePlans(snapshot) {
  return snapshot.plans.filter((plan) => plan.source_version === visibleVersion(snapshot));
}

function latestAgentEvent(snapshot) {
  return [...snapshot.events].reverse().find((event) =>
    event.name === "agent_investigation_completed" && event.data.source_version === visibleVersion(snapshot));
}

function rankKey(plan) {
  const critical = (plan.orders || []).filter((order) => order.priority === "critical").map((order) => order.delay_hours);
  return [Math.max(0, ...critical), plan.projected_customer_delay_hours, plan.late_units || 0, plan.incremental_cost_usd];
}
function byRank(a, b) {
  const left = rankKey(a), right = rankKey(b);
  return left.reduce((found, value, index) => found || value - right[index], 0);
}

function recommendedPlan(snapshot) {
  const plans = visiblePlans(snapshot);
  if (!plans.length) return null;
  const answer = latestAgentEvent(snapshot)?.data.answer || "";
  const id = window.LogiOpsIntent.recommendedPlanId(answer, plans);
  return plans.find((plan) => plan.id === id)
    || plans.find((plan) => answer.toLowerCase().includes(`recommend ${plan.label.toLowerCase()}`))
    || [...plans].sort(byRank)[0];
}

function allocationSummary(plan) {
  const units = new Map();
  for (const item of plan.allocations) units.set(item.source, (units.get(item.source) || 0) + item.units);
  return [...units].map(([source, count]) => `${count} via ${source.replaceAll("-", " ")}`).join(" · ");
}

function renderPlans(snapshot) {
  const container = $("plans");
  container.replaceChildren();
  container.setAttribute("role", "radiogroup");
  container.setAttribute("aria-label", "Resolution plans");
  const plans = visiblePlans(snapshot);
  if (!plans.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "Ask LogiOps to investigate to see the options.";
    container.append(empty);
    return;
  }
  const approval = visibleApproval(snapshot);
  const recommended = recommendedPlan(snapshot);
  if (approval) {
    state.selectedPlanId = approval.plan_id;
  } else if (!plans.some((plan) => plan.id === state.selectedPlanId)) {
    state.selectedPlanId = recommended?.id || plans[0].id;
  }
  for (const plan of plans) {
    const isRecommended = plan.id === recommended?.id;
    const card = document.createElement("label");
    card.className = `plan${plan.id === state.selectedPlanId ? " selected" : ""}${isRecommended ? " recommended" : ""}`;
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "plan";
    radio.value = plan.id;
    radio.checked = plan.id === state.selectedPlanId;
    radio.disabled = Boolean(approval || snapshot.executions.length);
    radio.addEventListener("change", () => {
      state.selectedPlanId = plan.id;
      renderPlans(snapshot);
      showOnDevice(snapshot);
      renderControls();
    });
    const description = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = plan.label;
    const badges = [];
    if (isRecommended) badges.push(["Agent pick", "badge"]);
    if (plan.id === snapshot.preference?.preferred_plan_id) badges.push(["Your preference", "badge preference"]);
    if (plan.projected_customer_delay_hours === 0) badges.push(["Zero delay", "badge"]);
    for (const [text, className] of badges) {
      const badge = document.createElement("span");
      badge.className = className;
      badge.textContent = text;
      title.append(badge);
    }
    const allocation = document.createElement("small");
    allocation.textContent = allocationSummary(plan);
    description.append(title, allocation);
    if ((plan.orders || []).length > 1) {
      const lines = document.createElement("div");
      lines.className = "order-lines";
      for (const order of plan.orders) {
        const line = document.createElement("span");
        line.className = order.delay_hours ? "late" : "";
        line.textContent = `${order.order_id} · ${order.customer}${order.priority === "critical" ? " (critical)" : ""}: `
          + (order.delay_hours ? `+${order.delay_hours} h` : "on time");
        lines.append(line);
      }
      description.append(lines);
    }
    const eta = document.createElement("div");
    eta.className = "plan-value";
    eta.textContent = formatDate(plan.projected_completion_eta);
    const etaLabel = document.createElement("small");
    etaLabel.textContent = `${plan.projected_customer_delay_hours}h delay`;
    eta.append(etaLabel);
    const cost = document.createElement("div");
    cost.className = "plan-value";
    cost.textContent = `$${plan.incremental_cost_usd}`;
    const costLabel = document.createElement("small");
    costLabel.textContent = "extra";
    cost.append(costLabel);
    card.append(radio, description, eta, cost);
    container.append(card);
  }
}

const RULE_NAMES = { balanced: "balanced ranking", cheapest_unless_critical_late: "cheapest unless a critical order is late" };

function describePreferences(prefs) {
  const parts = [RULE_NAMES[prefs.rule] || prefs.rule];
  parts.push(prefs.max_cost_usd === null || prefs.max_cost_usd === undefined ? "no spend cap" : `spend cap $${prefs.max_cost_usd}`);
  if (prefs.note) parts.push(`note “${prefs.note}”`);
  return parts.join(" · ");
}

function renderPreferenceLine(snapshot) {
  const line = $("preference-line");
  const preference = snapshot.preference;
  line.hidden = !preference;
  if (!preference) return;
  const strong = document.createElement("strong");
  strong.textContent = `Your preference → “${preference.preferred_plan_label}”. `;
  const text = preference.changes_pick ? preference.reason : "It agrees with the default pick.";
  line.replaceChildren(strong, document.createTextNode([text, ...preference.warnings].join(" ")));
}

function renderPreferences(snapshot) {
  const prefs = snapshot.operator_preferences;
  $("pref-saved").textContent = prefs ? `Saved ${formatDate(prefs.updated_at)}` : "None saved";
  const shown = prefs?.updated_at || null;
  if (state.prefsShown === shown) return;
  state.prefsShown = shown;
  $("pref-rule").value = prefs?.rule || "balanced";
  $("pref-cap").value = prefs?.max_cost_usd ?? "";
  $("pref-note").value = prefs?.note || "";
}

async function savePreferences(update) {
  const current = state.snapshot?.operator_preferences || {};
  const merged = {
    rule: current.rule || "balanced", max_cost_usd: current.max_cost_usd ?? null, note: current.note || "", ...update,
  };
  await request("/operator/preferences", "PUT", merged);
  state.prefsShown = undefined;
}

function preferenceEffect() {
  const preference = state.snapshot?.preference;
  if (!preference) return `I'll apply them to ${state.incidentId} once its plans are calculated.`;
  if (!preference.changes_pick) return `For ${state.incidentId}, they agree with the default pick, “${preference.default_plan_label}”.`;
  return `For ${state.incidentId}, they point to “${preference.preferred_plan_label}” instead of the default pick, `
    + `“${preference.default_plan_label}”. ${preference.reason} ${preference.warnings.join(" ")}`.trim();
}

function renderTimeline(events) {
  const timeline = $("timeline");
  timeline.replaceChildren();
  for (const event of [...events].reverse()) {
    const item = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = eventLabels[event.name] || event.name.replaceAll("_", " ");
    const when = document.createElement("small");
    when.textContent = formatDate(event.recorded_at);
    item.append(title, when);
    timeline.append(item);
  }
  $("event-count").textContent = `${events.length} event${events.length === 1 ? "" : "s"}`;
}

function inlineNodes(parts) {
  return parts.map((part) => {
    if (part.t === "text") return document.createTextNode(part.v);
    const node = document.createElement(part.t === "strong" ? "strong" : part.t === "em" ? "em" : "code");
    node.textContent = part.v;
    return node;
  });
}

function renderMarkdown(source) {
  const box = document.createElement("div");
  box.className = "markdown";
  const blocks = window.LogiOpsMarkdown.parseBlocks(source);
  const top = Math.min(...blocks.filter((block) => block.type === "h").map((block) => block.level));
  let previous = 2;
  for (const block of blocks) {
    let node;
    if (block.type === "hr") node = document.createElement("hr");
    else if (block.type === "h") {
      const level = Math.min(6, previous + 1, 3 + block.level - top);
      previous = level;
      node = document.createElement(`h${level}`);
      node.append(...inlineNodes(block.inline));
    }
    else if (block.type === "quote") { node = document.createElement("blockquote"); node.append(...inlineNodes(block.inline)); }
    else if (block.type === "ul" || block.type === "ol") {
      node = document.createElement(block.type);
      for (const item of block.items) { const li = document.createElement("li"); li.append(...inlineNodes(item)); node.append(li); }
    } else if (block.type === "table") {
      node = document.createElement("div");
      node.className = "table-scroll";
      node.tabIndex = 0;
      node.setAttribute("role", "region");
      node.setAttribute("aria-label", "Table from the agent's answer");
      const table = document.createElement("table");
      node.append(table);
      const head = table.createTHead().insertRow();
      for (const cell of block.head) {
        const empty = cell.every((part) => !part.v.trim());
        const th = document.createElement(empty ? "td" : "th");
        if (!empty) th.scope = "col";
        th.append(...inlineNodes(cell));
        head.append(th);
      }
      const body = table.createTBody();
      for (const row of block.rows) {
        const tr = body.insertRow();
        for (const cell of row) tr.insertCell().append(...inlineNodes(cell));
      }
    } else { node = document.createElement("p"); node.append(...inlineNodes(block.inline)); }
    box.append(node);
  }
  return box;
}

function renderConversation() {
  const list = $("conversation");
  list.replaceChildren();
  const entries = state.conversation.length ? state.conversation : [{ role: "assistant", text: welcomeText() }];
  for (const entry of entries) {
    const item = document.createElement("li");
    item.className = `turn ${entry.role}`;
    const who = document.createElement("span");
    who.className = "turn-role";
    who.textContent = entry.role === "user" ? "You" : "LogiOps";
    const text = entry.role === "assistant" ? renderMarkdown(entry.text) : document.createElement("p");
    if (entry.role !== "assistant") text.textContent = entry.text;
    item.append(who, text);
    if (entry.check) {
      const badge = document.createElement("span");
      badge.className = `check-badge${entry.check.passed ? "" : " failed"}`;
      badge.textContent = entry.check.text;
      item.append(badge);
    }
    if (entry.meta) {
      const meta = document.createElement("small");
      meta.textContent = entry.meta;
      item.append(meta);
    }
    list.append(item);
  }
  list.scrollTop = list.scrollHeight;
}

function welcomeText() {
  const open = state.inbox.filter((item) => item.status !== "verified");
  if (!state.inbox.length) {
    return `Hi, I'm LogiOps. Ask me what's happening with ${state.incidentId}, and I'll investigate it with the MCP tools.`;
  }
  const critical = open.filter((item) => item.priority === "critical").map((item) => item.incident_id);
  const atRisk = open.filter((item) => item.critical_units_at_risk > 0)
    .map((item) => `${item.incident_id} has ${item.critical_units_at_risk} critical units nothing on hand delivers in time`);
  const queue = open.length
    ? `${open.length} open incident${open.length === 1 ? "" : "s"} in the inbox`
      + (critical.length ? `; ${critical.join(" and ")} ${critical.length === 1 ? "has a critical order" : "have critical orders"}` : "")
      + (atRisk.length ? `, and ${atRisk.join(" and ")}` : "")
    : "Every incident in the inbox is resolved";
  return `Hi, I'm LogiOps. ${queue}. Ask “any delays today?” for my briefing, or ask what's happening with ${state.incidentId}.`;
}

function memorySession() {
  try {
    let id = sessionStorage.getItem("logiops-memory-session");
    if (!id) {
      id = `s-${randomText(12)}`;
      sessionStorage.setItem("logiops-memory-session", id);
    }
    return id;
  } catch (_) {
    return null;
  }
}

function remember(role, text) {
  const session = memorySession();
  if (!session || (state.auth.enabled && !state.session)) return;
  const headers = { "Content-Type": "application/json" };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  fetch("/memory/turns", {
    method: "POST", headers, cache: "no-store",
    body: JSON.stringify({ session, role, text: String(text).slice(0, 4000), incident: state.incidentId }),
  }).catch(() => {});
}

async function recallMemory() {
  if (state.auth.enabled && !state.session) return;
  let recalled;
  try {
    recalled = await request(`/memory?session=${encodeURIComponent(memorySession() || "")}`);
  } catch (_) {
    return;
  }
  state.memoryIncident = recalled.last_incident || null;
  if (recalled.welcome && !state.conversation.some((turn) => turn.role === "user")) {
    say("assistant", recalled.welcome, "welcome back · from memory", recalled.welcome);
  }
}

function say(role, text, meta, spoken, check) {
  state.conversation.push({ role, text, meta, check });
  renderConversation();
  if (!state.forgetting && !String(meta || "").startsWith("welcome back")) remember(role, role === "assistant" ? (spoken || window.LogiOpsMarkdown.plainText(text)) : text);
  if (role !== "assistant") {
    device("heard", text);
    return;
  }
  const speaking = speechOn();
  device("reply", text, spoken, speaking);
  if (speaking) speak(spoken || window.LogiOpsMarkdown.plainText(text));
}

function speechOn() {
  return $("speak-replies").checked && (state.voice.engine === "polly" || "speechSynthesis" in window);
}

function stopSpeaking({ quiet = false } = {}) {
  state.speechTurn += 1;
  clearTimeout(state.fillerTimer);
  clearTimeout(state.speechTimer);
  let stopped = false;
  if (state.audio) {
    state.audio.pause();
    state.audio = null;
    stopped = true;
  }
  if ("speechSynthesis" in window && (window.speechSynthesis.speaking || window.speechSynthesis.pending)) {
    window.speechSynthesis.cancel();
    stopped = true;
  }
  if (stopped && !quiet) device("voice", "speech-end");
}

function browserSpeak(line, done) {
  if (!("speechSynthesis" in window)) {
    done();
    return;
  }
  const utterance = new SpeechSynthesisUtterance(line);
  utterance.lang = "en-US";
  utterance.addEventListener("end", done);
  utterance.addEventListener("error", done);
  window.speechSynthesis.speak(utterance);
}

async function speak(line, { filler = false } = {}) {
  stopSpeaking({ quiet: true });
  const turn = state.speechTurn;
  const done = () => {
    if (turn !== state.speechTurn) return;
    clearTimeout(state.speechTimer);
    if (!filler) device("voice", "speech-end");
  };
  state.speechTimer = setTimeout(done, 30000);
  if (state.voice.engine === "polly") {
    try {
      const headers = { "Content-Type": "application/json" };
      if (state.token) headers.Authorization = `Bearer ${state.token}`;
      const response = await fetch("/voice/speech", { method: "POST", headers, body: JSON.stringify({ text: line }), cache: "no-store" });
      if (turn !== state.speechTurn) return;
      if (response.ok) {
        const url = URL.createObjectURL(await response.blob());
        if (turn !== state.speechTurn) {
          URL.revokeObjectURL(url);
          return;
        }
        const audio = new Audio(url);
        state.audio = audio;
        const finish = () => {
          URL.revokeObjectURL(url);
          if (state.audio === audio) state.audio = null;
          done();
        };
        audio.addEventListener("ended", finish);
        audio.addEventListener("error", finish);
        await audio.play();
        return;
      }
    } catch (_) {
      if (turn !== state.speechTurn) return;
    }
  }
  browserSpeak(line, done);
}

function startFiller() {
  clearTimeout(state.fillerTimer);
  if (!speechOn()) return;
  state.fillerTimer = setTimeout(() => {
    const fillers = state.voice.fillers.length ? state.voice.fillers : ["One moment, I'm still working on it."];
    speak(fillers[Math.floor(Math.random() * fillers.length)], { filler: true });
  }, 2500);
}

async function loadVoice() {
  try {
    state.voice = await request("/voice/config");
  } catch (_) {
    return;
  }
  if (state.voice.engine === "polly") {
    $("speak-toggle").hidden = false;
    $("speak-replies").checked = true;
    $("speak-engine").textContent = ` (Amazon Polly · ${state.voice.voice})`;
  }
}

function showOnDevice(snapshot) {
  const plan = visiblePlans(snapshot).find((item) => item.id === state.selectedPlanId) || null;
  device("show", snapshot, plan, state.inbox.find((item) => item.incident_id === snapshot.state.incident_id));
}

function renderControls() {
  const snapshot = state.snapshot;
  const approved = Boolean(snapshot && visibleApproval(snapshot));
  const executed = Boolean(snapshot?.executions.length);
  const hasCurrentPlan = Boolean(snapshot?.plans.some((plan) => plan.source_version === snapshot.source_version));
  $("ask").disabled = state.busy || !snapshot;
  $("ask-input").disabled = state.busy || !snapshot;
  $("mic").disabled = state.busy || !snapshot;
  for (const chip of document.querySelectorAll(".chip")) chip.disabled = state.busy || !snapshot;
  $("approve").disabled = state.busy || !hasCurrentPlan || !state.selectedPlanId || approved || executed;
  const selected = snapshot && !approved && !executed && visiblePlans(snapshot).find((plan) => plan.id === state.selectedPlanId);
  $("approve").textContent = selected ? `Approve “${selected.label}”` : "Approve selected plan";
  $("execute").disabled = state.busy || !approved || executed;
  $("reset").disabled = state.busy;
  $("banner-reset").disabled = state.busy;
  $("set-stock").disabled = state.busy || !snapshot || executed || !localWarehouse(snapshot);
  for (const id of ["pref-rule", "pref-cap", "pref-note", "pref-save", "pref-clear"]) $(id).disabled = state.busy || !snapshot;
  $("stock-input").disabled = state.busy || !snapshot || !localWarehouse(snapshot);
  $("connect").disabled = state.busy;
}

function localWarehouse(snapshot) {
  return Object.keys(snapshot.state.inventory || {})[0] || null;
}

function renderInbox() {
  const list = $("inbox");
  list.replaceChildren();
  const tag = (className, text) => {
    const node = document.createElement("span");
    node.className = className;
    node.textContent = text;
    return node;
  };
  for (const item of state.inbox) {
    const entry = document.createElement("li");
    const card = document.createElement("button");
    card.type = "button";
    card.className = "incident-card";
    card.setAttribute("aria-pressed", String(item.incident_id === state.incidentId));
    const top = tag("incident-top", "");
    top.append(tag("incident-id", item.incident_id), tag("kind", item.kind_label));
    if (item.priority === "critical") top.append(tag("critical", "Critical order"));
    if (item.critical_units_at_risk > 0) top.append(tag("at-risk", `${item.critical_units_at_risk} critical units at risk`));
    top.append(tag("state", item.status));
    if (item.incident_id === state.briefingPick) top.append(tag("start-here", "Start here"));
    const due = document.createElement("small");
    due.textContent = `${item.route} · ${item.units} units · due ${formatDate(item.due_eta)}`;
    card.append(top, tag("incident-text", item.title), due);
    card.addEventListener("click", () => selectIncident(item.incident_id).catch(() => {}));
    entry.append(card);
    list.append(entry);
  }
}

function render(snapshot) {
  state.snapshot = snapshot;
  if (state.app && (state.app.incidentId !== snapshot.state.incident_id || state.app.version !== visibleVersion(snapshot))) hideMcpApp();
  $("connection").textContent = "Connected";
  $("connection").className = "connection ready";
  renderInbox();
  const incident = snapshot.state;
  const shipment = incident.shipment;
  const units = incident.orders.reduce((sum, order) => sum + order.quantity, 0);
  document.title = `LogiOps AI · ${incident.incident_id}`;
  $("incident-id").textContent = incident.incident_id;
  $("incident-title").textContent = incident.title;
  $("incident-route").textContent = `${shipment.origin} → ${shipment.destination} · ${units} units of ${shipment.sku} · `
    + (incident.orders.length === 1 ? "1 order" : `${incident.orders.length} orders`);
  $("incident-status").textContent = incident.status;
  $("promise-label").textContent = incident.orders.length === 1 ? "Customer promise" : "Shipment's original ETA";
  const warehouse = localWarehouse(snapshot);
  $("stock-value").textContent = warehouse ? `${incident.inventory[warehouse].available} units` : "None";
  $("stock-label").textContent = warehouse ? `${warehouse[0].toUpperCase()}${warehouse.slice(1)} warehouse` : "No local warehouse";
  $("stock-scope").textContent = warehouse ? `(${warehouse[0].toUpperCase()}${warehouse.slice(1)} warehouse; invalidates approvals)` : "(this incident has no local warehouse)";
  if (state.stockFor !== incident.incident_id) {
    state.stockFor = incident.incident_id;
    $("stock-input").max = String(units);
    $("stock-input").value = warehouse ? String(Math.max(0, incident.inventory[warehouse].available - 1)) : "";
  }
  $("chip-status").dataset.say = `What's happening with shipment ${incident.incident_id}, and which plan should we choose?`;
  $("chip-status").textContent = `What's happening with ${incident.incident_id}?`;
  $("original-eta").textContent = formatDate(shipment.original_eta);
  $("delayed-eta").textContent = formatDate(shipment.delayed_eta);
  const delay = Math.round((new Date(shipment.delayed_eta) - new Date(shipment.original_eta)) / 3600000);
  $("delay-hours").textContent = `+${delay} hours`;
  const agentEvent = latestAgentEvent(snapshot);
  $("agent-mode").textContent = agentEvent ? agentEvent.data.mode : "Agent";
  if (!state.conversation.length && agentEvent) {
    state.conversation.push({ role: "assistant", text: agentEvent.data.display_answer || agentEvent.data.answer, meta: traceSummary(agentEvent.data), check: checkBadge(agentEvent.data) });
  }
  renderConversation();
  renderPreferenceLine(snapshot);
  renderPreferences(snapshot);
  renderPlans(snapshot);
  showOnDevice(snapshot);
  renderTimeline(snapshot.events);
  const execution = snapshot.executions[0];
  $("execution-state").textContent = execution ? "Operationally verified" : visibleApproval(snapshot) ? "Approved · ready" : "Waiting for approval";
  $("execution-result").hidden = !execution;
  $("state-banner").hidden = !execution;
  if (execution) {
    const plan = snapshot.plans.find((item) => item.id === execution.plan_id);
    $("state-banner-text").textContent = `${incident.incident_id} was already executed with “${plan?.label || execution.plan_id}” and verified. Questions now refer to that result; reset this incident to run the whole flow again.`;
  }
  if (execution) {
    $("execution-result").textContent = executionSummary(snapshot, execution);
  }
  showBooking((snapshot.bookings || []).at(-1) || null);
  renderControls();
}

function checkBadge(run) {
  if (!run.evaluations?.length) return null;
  if (!run.grounded) {
    const issue = run.evaluations[run.evaluations.length - 1].issues[0] || "";
    return { passed: false, text: `Did not pass the data check: ${issue}` };
  }
  return { passed: true, text: run.evaluations.length > 1 ? "Checked against the data after one revision" : "Checked against the data" };
}

function noteCheck(run) {
  if (run.evaluations?.length && !run.grounded) {
    message("This answer did not pass the automatic check against the incident's data. The plan cards are calculated by code; rely on them.");
  }
}

function noteFallback(run) {
  if (run.fallback === "daily_budget") {
    message("Today's live model budget is used, so answers come from the scripted replay until midnight, Lima time.", true);
  }
}

function traceSummary(run) {
  const tokens = (run.usage?.inputTokens || 0) + (run.usage?.outputTokens || 0);
  const fallback = run.fallback === "daily_budget" ? " · daily live budget used" : "";
  return `${run.tool_trace.length} MCP calls · ${run.mode} mode${fallback} · ${tokens} tokens${run.truncated ? " · truncated" : ""}`;
}

function executionSummary(snapshot, execution) {
  const accounted = execution.accounted_units
    ?? snapshot.state.shipment.units_on_delayed_route + execution.fulfillments.reduce((sum, item) => sum + item.units, 0);
  return `Verified: ${accounted} units accounted for · $${execution.incremental_cost_usd} extra · ${execution.notifications.length} simulated notifications. Customer delay: ${execution.projected_customer_delay_hours}h (projected).`;
}

async function refresh() {
  state.inbox = (await request("/incidents")).incidents;
  if (!state.inbox.some((item) => item.incident_id === state.incidentId)) {
    state.incidentId = state.inbox[0]?.incident_id || DEFAULT_INCIDENT;
    history.replaceState(null, "", `#${encodeURIComponent(state.incidentId)}`);
  }
  render(await request(incidentPath()));
}

async function selectIncident(id) {
  if (state.busy || id === state.incidentId) return;
  state.conversations[state.incidentId] = state.conversation;
  state.selections[state.incidentId] = state.selectedPlanId;
  state.incidentId = id;
  state.conversation = state.conversations[id] || [];
  state.selectedPlanId = state.selections[id] || null;
  state.awaitingExecute = false;
  state.pendingApproval = null;
  state.pendingPurchase = null;
  history.replaceState(null, "", `#${encodeURIComponent(id)}`);
  hideMcpApp("incident changed");
  await act(refresh, "");
  renderAlertBell();
}

async function act(work, success) {
  setBusy(true);
  message("");
  try {
    await work();
    await refresh();
    if (success) message(success, true);
  } catch (error) {
    message(error.message || String(error));
    if (error.status === 401 && state.auth.enabled) {
      if (state.session) keepSession(null);
      $("link-account").focus();
    } else if (error.status === 401) {
      storeToken("");
      $("connection").textContent = "Token required";
      $("connection").className = "connection error";
      if (!state.snapshot) $("incident-status").textContent = "Locked";
      $("access-token").focus();
    }
    throw error;
  } finally { setBusy(false); }
}

async function approvePlan(plan) {
  const approvedBy = $("approver").value.trim();
  if (!plan || !approvedBy) throw new Error("Select a plan and enter an approver name.");
  await request(incidentPath("/approvals"), "POST", {
    plan_id: plan.id, source_version: plan.source_version, approved_by: approvedBy,
  });
}

async function executeApproved() {
  const approval = visibleApproval(state.snapshot);
  if (!approval) throw new Error("No plan is approved for the current incident version.");
  await request(incidentPath("/execute"), "POST", {
    plan_id: approval.plan_id, source_version: approval.source_version,
  });
}

function namedPlanKinds(text) {
  const found = planKeywords.find(([, pattern]) => pattern.test(text));
  return found ? found[0] : null;
}

function planFromUtterance(text) {
  const plans = visiblePlans(state.snapshot);
  const preferred = state.snapshot.preference && plans.find((plan) => plan.id === state.snapshot.preference.preferred_plan_id);
  if (preferred && /\b(?:preferred|my preference)\b/.test(text)) return preferred;
  const selector = window.LogiOpsIntent.planSelector(text);
  if (selector.cheapest) {
    return [...plans].sort((a, b) => a.incremental_cost_usd - b.incremental_cost_usd || byRank(a, b))[0] || null;
  }
  if (selector.cost !== undefined) {
    const priced = plans.filter((plan) => plan.incremental_cost_usd === selector.cost);
    return priced.length === 1 ? priced[0] : null;
  }
  const kinds = namedPlanKinds(text);
  if (kinds) return kinds.map((kind) => plans.find((plan) => plan.kind === kind)).find(Boolean) || null;
  return recommendedPlan(state.snapshot);
}

function dollars(value) {
  return `$${Number(value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function newPurchaseKey() {
  const random = window.crypto?.randomUUID ? window.crypto.randomUUID() : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
  return `buy-${random}`;
}

function spelled(number) {
  return String(number).replace("-", "").split("").join(" ");
}

function purchaseReadback(purchase, plan) {
  const quote = purchase.quote;
  const card = String(quote.payment_method).replace(/\s*\(simulated\)$/i, "").toLowerCase();
  const breakdown = `carriers and services ${dollars(quote.base_usd)}, service fee ${dollars(quote.service_fee_usd)}, `
    + `IGV 18% ${dollars(quote.igv_usd)}, total ${dollars(quote.total_usd)}, charged to the ${card}`;
  if (!purchase.approve) {
    const text = `To book “${quote.plan_label}”: ${breakdown}. Say “yes” to pay, or “no”.`;
    return { text, spoken: text };
  }
  const delay = plan.projected_customer_delay_hours ? `${plan.projected_customer_delay_hours} hours of delay` : "no delay";
  const late = (plan.orders || []).filter((order) => order.priority === "critical" && order.delay_hours > 0);
  const warning = late.length ? ` It leaves the critical order for ${late.map((order) => order.customer).join(" and ")} late.` : "";
  const text = `To approve “${quote.plan_label}” (${delay}) and book it: ${breakdown}.${warning} `
    + "Say “yes” to approve and pay, or “no”.";
  return { text, spoken: text };
}

function showBooking(booking) {
  const box = $("booking");
  if (!booking) {
    box.hidden = true;
    box.replaceChildren();
    device("receipt", null);
    return;
  }
  const head = document.createElement("p");
  head.className = "booking-head";
  head.textContent = `Booked ${booking.number} · ${dollars(booking.total_usd)} charged once (simulated payment)`;
  const list = document.createElement("dl");
  list.className = "booking-lines";
  const rows = [
    ...booking.lines.map((line) => [`${line.service}, ${line.units} units`, "cost_usd" in line ? dollars(line.cost_usd) : "included"]),
    ["Carriers and services", dollars(booking.base_usd)], ["Service fee", dollars(booking.service_fee_usd)],
    ["IGV 18%", dollars(booking.igv_usd)], ["Total", dollars(booking.total_usd)],
  ];
  for (const [term, value] of rows) {
    const dt = document.createElement("dt");
    dt.textContent = term;
    const dd = document.createElement("dd");
    dd.textContent = value;
    list.append(dt, dd);
  }
  const open = document.createElement("button");
  open.type = "button";
  open.className = "secondary";
  open.textContent = "Open printable receipt";
  open.addEventListener("click", () => openReceipt(booking.number).catch((error) => message(error.message || String(error))));
  box.replaceChildren(head, list, open);
  box.hidden = false;
  device("receipt", booking);
}

async function openReceipt(number) {
  const headers = state.token ? { Authorization: `Bearer ${state.token}` } : {};
  const response = await fetch(`/bookings/${encodeURIComponent(number)}/receipt`, { headers, cache: "no-store" });
  if (!response.ok) throw new Error(explainError(response.status, "The receipt could not be opened."));
  const url = URL.createObjectURL(new Blob([await response.text()], { type: "text/html" }));
  window.open(url, "_blank");
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

function renderAlertBell() {
  const elsewhere = state.alerts.filter((alert) => alert.incident_id !== state.incidentId);
  const bell = $("alerts-bell");
  bell.hidden = !elsewhere.length;
  bell.textContent = `${elsewhere.length} alert${elsewhere.length === 1 ? "" : "s"} · ${elsewhere[0]?.incident_id || ""}`;
  bell.setAttribute("aria-label", `${elsewhere.length} proactive alert${elsewhere.length === 1 ? "" : "s"}; open ${elsewhere[0]?.incident_id || ""}`);
}

async function announceAlert(alert) {
  try {
    await request(`/alerts/${encodeURIComponent(alert.id)}/dismiss`, "POST");
  } catch (_) {
    return;
  }
  state.alerts = state.alerts.filter((item) => item.id !== alert.id);
  renderAlertBell();
  state.pendingApproval = null;
  state.awaitingExecute = false;
  if (state.pendingPurchase?.incidentId === alert.incident_id || storedPurchase()?.incidentId === alert.incident_id) forgetPurchase();
  state.selectedPlanId = alert.new_plan?.plan_id || null;
  await refresh().catch(() => {});
  say("assistant", alert.message, "proactive alert · nothing approved", alert.spoken);
}

async function checkAlerts() {
  if (!state.snapshot || state.busy || document.hidden) return;
  try {
    state.alerts = (await request("/alerts")).alerts;
  } catch (_) {
    return;
  }
  renderAlertBell();
  const here = state.alerts.find((alert) => alert.incident_id === state.incidentId);
  if (here && !state.busy) await announceAlert(here);
}

async function startPurchase(lower) {
  const snapshot = state.snapshot;
  if (!visiblePlans(snapshot).length) {
    say("assistant", "There are no plans for the current data yet. Ask me to investigate first.");
    return;
  }
  const approval = visibleApproval(snapshot);
  const lockedId = snapshot.executions[0]?.plan_id || approval?.plan_id;
  const locked = lockedId && snapshot.plans.find((plan) => plan.id === lockedId);
  const named = namedPlanKinds(lower);
  if (locked && named && !named.includes(locked.kind)) {
    say("assistant", `The approved plan is “${locked.label}”, so that's the only one I can book. Nothing was charged.`);
    return;
  }
  const plan = locked || planFromUtterance(lower);
  if (!plan) {
    const options = visiblePlans(snapshot).map((item) => `“${item.label}” ($${item.incremental_cost_usd})`).join(", ");
    say("assistant", `That plan isn't available for the current data. The options are ${options}.`);
    return;
  }
  const booked = (snapshot.bookings || []).find((item) => item.plan_id === plan.id);
  if (booked) {
    say("assistant", `“${plan.label}” is already booked as ${booked.number}: ${dollars(booked.total_usd)} was charged once. Nothing more to pay.`);
    showBooking(booked);
    return;
  }
  if (!plan.incremental_cost_usd) {
    say("assistant", `“${plan.label}” uses no paid carrier or service, so there's nothing to book.`);
    return;
  }
  let quote;
  await act(async () => { quote = await request(incidentPath("/bookings/quote"), "POST", { plan_id: plan.id }); }, "");
  const purchase = {
    incidentId: state.incidentId, planId: plan.id, sourceVersion: plan.source_version, approve: !quote.approved,
    quote, key: newPurchaseKey(),
  };
  keepPurchase(purchase);
  const readback = purchaseReadback(purchase, plan);
  say("assistant", readback.text, "price read-back · nothing charged yet", readback.spoken);
}

async function confirmPurchase(purchase) {
  if (Date.parse(purchase.quote.expires_at) <= Date.now()) {
    forgetPurchase();
    say("assistant", "That price expired, so nothing was charged. Say “book it” for a new quote.");
    return;
  }
  const plan = state.snapshot.plans.find((item) => item.id === purchase.planId && item.source_version === purchase.sourceVersion);
  const current = plan && (plan.source_version === state.snapshot.source_version || state.snapshot.executions.some((item) => item.plan_id === plan.id));
  if (!current) {
    forgetPurchase();
    say("assistant", "The data changed after I read that price back, so nothing was approved or charged. Ask me again.");
    return;
  }
  let approvedNow = false;
  if (purchase.approve && !visibleApproval(state.snapshot) && !state.snapshot.executions.length) {
    await act(() => approvePlan(plan), "");
    approvedNow = true;
    keepPurchase({ ...purchase, approve: false });
  }
  let booking;
  try {
    await act(async () => {
      booking = await request(`/quotes/${encodeURIComponent(purchase.quote.quote_id)}/confirm`, "POST", {
        confirmed_total_usd: purchase.quote.total_usd, idempotency_key: purchase.key,
      });
    }, "");
  } catch (error) {
    const retry = !error.status || error.status >= 500;
    if (!retry) forgetPurchase();
    say("assistant", `${approvedNow ? `Approved “${plan.label}”, but the` : "The"} booking didn't go through: ${error.message || error}`
      + (retry ? " Say “yes” to try again; it never charges twice." : ""));
    return;
  }
  forgetPurchase();
  showBooking(booking);
  say("assistant", `${approvedNow ? "Approved. " : ""}${booking.confirmation} The receipt is in the execute panel.`,
    `booking · ${booking.number}`,
    `${approvedNow ? "Approved, and booked. " : "Booked. "}${dollars(booking.total_usd)} charged. Your confirmation number is ${spelled(booking.number)}.`);
}

function approvalReadback(plan) {
  const delay = plan.projected_customer_delay_hours ? `${plan.projected_customer_delay_hours} hours of delay` : "no delay";
  const late = (plan.orders || []).filter((order) => order.priority === "critical" && order.delay_hours > 0);
  const warning = late.length ? `, and it leaves the critical order for ${late.map((order) => order.customer).join(" and ")} late` : "";
  return `Approve “${plan.label}” for $${plan.incremental_cost_usd} extra, ${delay}${warning}?`;
}

async function handleUtterance(raw) {
  const text = raw.trim();
  if (!text || state.busy) return;
  stopSpeaking();
  const mentioned = window.LogiOpsIntent.mentionedIncident(text, state.inbox.map((item) => item.incident_id));
  if (mentioned && mentioned !== state.incidentId) {
    await selectIncident(mentioned).catch(() => {});
    if (state.incidentId !== mentioned) return;
  }
  state.forgetting = window.LogiOpsIntent.isForgetMe(text);
  say("user", text);
  const lower = text.toLowerCase();
  if (window.LogiOpsIntent.isStartOver(text)) {
    forgetPurchase();
    Object.assign(state, { pendingApproval: null, awaitingExecute: false, selectedPlanId: null, conversation: state.conversation.slice(-1) });
    state.selections[state.incidentId] = null;
    hideMcpApp();
    say("assistant", "Okay, starting over. Nothing was changed or approved. Ask about your queue, or about an incident.",
      undefined, "Okay, starting over. Nothing was changed.");
    return;
  }
  if (window.LogiOpsIntent.isCapabilities(text)) {
    say("assistant", CAPABILITIES_TEXT, "help", CAPABILITIES_SPOKEN);
    return;
  }
  const pending = state.pendingApproval;
  state.pendingApproval = null;
  const purchase = state.pendingPurchase;
  state.pendingPurchase = null;
  const preference = window.LogiOpsIntent.parsePreference(text);
  if (preference) {
    state.awaitingExecute = false;
    try {
      if (preference.forget) {
        await act(() => request("/operator/preferences", "DELETE"), "");
        say("assistant", "Done. I forgot your saved preferences; plans are picked by the default ranking again.");
      } else {
        await act(() => savePreferences(preference.update), "");
        say("assistant", `Saved for every incident: ${describePreferences(state.snapshot.operator_preferences)}. ${preferenceEffect()} `
          + "Preferences never approve anything; you still approve the plan.");
      }
    } catch (error) {
      say("assistant", `I couldn't save that: ${error.message || error}`);
    }
    return;
  }
  if (window.LogiOpsIntent.isBriefing(text) && !mentioned) {
    state.awaitingExecute = false;
    try {
      let run;
      await act(async () => { run = await request("/agent/briefing", "POST", { question: text }); }, "");
      state.briefingPick = run.start_with;
      renderInbox();
      say("assistant", run.answer, `briefing · ${traceSummary(run)}`, run.spoken, checkBadge(run));
      device("trace", run);
      noteFallback(run);
      noteCheck(run);
    } catch (error) {
      say("assistant", `I couldn't do that: ${error.message || error}`);
    }
    return;
  }
  let command = window.LogiOpsIntent.parseCommand(text);
  if (command === "open") {
    if (mentioned) {
      const item = state.inbox.find((entry) => entry.incident_id === mentioned);
      say("assistant", `Opened ${mentioned}: ${item?.title || "incident"}. Ask me what's happening, or say “investigate”.`);
      return;
    }
    command = null;
  }
  const awaitingExecute = state.awaitingExecute;
  state.awaitingExecute = false;
  try {
    if (command === "reset") {
      const id = state.incidentId;
      forgetPurchase();
      await act(() => request("/demo/reset", "POST", { incident_id: id }), "");
      state.selectedPlanId = null;
      state.conversation = [];
      hideMcpApp();
      say("assistant", `Done. ${id} is back to its original state.`);
    } else if (command === "book") {
      await startPurchase(lower);
    } else if (command === "confirm" && purchase) {
      await confirmPurchase(purchase);
    } else if (command === "decline") {
      if (purchase || storedPurchase()) {
        forgetPurchase();
        say("assistant", "Okay, nothing was booked or charged.");
      } else {
        say("assistant", pending ? "Okay, nothing was approved." : "Okay. Ask me anything else about the queue or this incident.");
      }
    } else if (command === "forget_me") {
      if (state.auth.enabled && !state.session) {
        say("assistant", "I don't remember guests, so there's nothing to forget.");
      } else {
        let result;
        await act(async () => { result = await request("/memory", "DELETE"); }, "");
        state.memoryIncident = null;
        say("assistant", `Done. I forgot our earlier conversations (${result.forgotten} item${result.forgotten === 1 ? "" : "s"}). `
          + "Your saved preferences stay until you say “forget my preferences”.", "memory cleared");
      }
      state.forgetting = false;
    } else if (command === "pick_up") {
      const target = state.memoryIncident;
      if (!target) {
        say("assistant", "I don't have an earlier conversation to pick up. Ask about your queue, or about an incident.");
      } else {
        if (target !== state.incidentId) {
          await selectIncident(target);
          state.conversation.push({ role: "user", text });
        }
        say("assistant", `Back on ${target}. Ask what's happening, or say “approve the recommended plan”.`);
      }
    } else if (command === "link") {
      if (state.session) say("assistant", `You're already signed in as ${state.session.username}.`);
      else await linkAccount();
    } else if (command === "unlink") {
      if (!state.session) {
        say("assistant", "You're not signed in.");
      } else {
        signOut();
        say("assistant", "Signed out on this page. You're a guest again: you can read and ask, but not act.");
      }
    } else if (command === "resume") {
      const parked = storedPurchase();
      if (!parked) {
        say("assistant", "There's no booking waiting. Say “book it” to price the approved plan's carriers.");
        return;
      }
      if (parked.incidentId !== state.incidentId) {
        await selectIncident(parked.incidentId);
        if (state.incidentId !== parked.incidentId) return;
      }
      const plan = state.snapshot.plans.find((item) => item.id === parked.planId);
      if (!plan) {
        forgetPurchase();
        say("assistant", "That booking no longer matches the incident's data, so nothing was charged. Say “book it” for a new quote.");
        return;
      }
      keepPurchase(parked);
      const readback = purchaseReadback(parked, plan);
      say("assistant", readback.text, "price read-back · nothing charged yet", readback.spoken);
    } else if (command === "approve") {
      if (!visiblePlans(state.snapshot).length) {
        say("assistant", "There are no plans for the current data yet. Ask me to investigate first.");
        return;
      }
      const plan = planFromUtterance(lower);
      if (!plan) {
        const options = visiblePlans(state.snapshot).map((item) => `“${item.label}” ($${item.incremental_cost_usd})`).join(", ");
        say("assistant", `That plan isn't available for the current data. The options are ${options}.`);
        return;
      }
      state.pendingApproval = { planId: plan.id, sourceVersion: plan.source_version };
      say("assistant", `${approvalReadback(plan)} Say “yes” to approve it, or ask me anything else.`);
    } else if (command === "confirm" && pending) {
      const plan = visiblePlans(state.snapshot)
        .find((item) => item.id === pending.planId && item.source_version === pending.sourceVersion);
      if (!plan) {
        say("assistant", "The data changed after I read that plan back, so nothing was approved. Ask me again.");
        return;
      }
      try {
        await act(() => approvePlan(plan), "");
      } catch (error) {
        state.pendingApproval = pending;
        throw error;
      }
      say("assistant", `Approved “${plan.label}” for version ${plan.source_version}. Say “execute it” when you're ready.`);
      state.awaitingExecute = true;
    } else if (command === "execute" || (command === "confirm" && awaitingExecute && visibleApproval(state.snapshot))) {
      const approval = visibleApproval(state.snapshot);
      const approved = approval && state.snapshot.plans.find((plan) => plan.id === approval.plan_id);
      const named = namedPlanKinds(lower);
      if (approved && named && !named.includes(approved.kind)) {
        const wanted = named.map((kind) => visiblePlans(state.snapshot).find((plan) => plan.kind === kind)).find(Boolean);
        say("assistant", `The approved plan is “${approved.label}”, so nothing was executed. ${wanted ? `Approve “${wanted.label}” first if you want it instead.` : "The plan you named isn't available for the current data."}`);
        return;
      }
      if (state.snapshot?.executions.length) {
        say("assistant", `${state.incidentId} was already executed. ${executionSummary(state.snapshot, state.snapshot.executions[0])} Reset this incident to run the flow again.`);
        return;
      }
      await act(executeApproved, "");
      const execution = state.snapshot.executions[0];
      say("assistant", `The plan was executed. ${executionSummary(state.snapshot, execution)} Delivery is projected, not physically confirmed.`);
    } else if (command === "confirm") {
      say("assistant", "Nothing is waiting for a “yes” right now. Say “approve the recommended plan” or “book it”, and I'll read it back first.");
    } else {
      const current = latestAgentEvent(state.snapshot);
      const stale = !current || current.data.source_version !== visibleVersion(state.snapshot);
      const executed = Boolean(state.snapshot?.executions.length);
      if (executed && stale) {
        say("assistant", "This incident was already executed without an investigation to refer to. Reset this incident to start over.");
        return;
      }
      const fresh = !executed && (stale || /\b(investigate|re-?check|refresh|start again|what(?:'s| is) happening)\b/.test(lower));
      const history = state.conversation.slice(0, -1).slice(-6).map(({ role, text: turn }) => ({ role, text: turn.slice(0, 1000) }));
      let run;
      await act(async () => {
        run = fresh
          ? await request(incidentPath("/agent/investigate"), "POST", { question: text })
          : await request(incidentPath("/agent/ask"), "POST", { question: text, history });
      }, "");
      say("assistant", run.answer, `${fresh ? "investigation" : "follow-up"} · ${traceSummary(run)}`, run.spoken, checkBadge(run));
      device("trace", run);
      noteFallback(run);
      noteCheck(run);
      if (fresh) {
        showMcpApp(run).catch((error) => {
          console.warn("MCP App failed:", error);
          showMcpAppNote(`The interactive card could not be loaded (${error?.message || error}). The plans are listed below.`);
        });
      }
    }
  } catch (error) {
    say("assistant", `I couldn't do that: ${error.message || error}`);
  }
}

function setUpVoice() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if ("speechSynthesis" in window) $("speak-toggle").hidden = false;
  if (!Recognition) return;
  const mic = $("mic");
  mic.hidden = false;
  const recognition = new Recognition();
  recognition.lang = "en-US";
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;
  recognition.addEventListener("result", (event) => {
    const transcript = event.results[0][0].transcript;
    $("ask-input").value = "";
    handleUtterance(transcript);
  });
  recognition.addEventListener("end", () => {
    mic.textContent = "Speak";
    mic.setAttribute("aria-pressed", "false");
    device("voice", "listen-end");
  });
  recognition.addEventListener("error", (event) => {
    if (event.error !== "no-speech" && event.error !== "aborted") message(`Voice input unavailable: ${event.error}`);
  });
  mic.addEventListener("click", () => {
    if (mic.getAttribute("aria-pressed") === "true") {
      recognition.stop();
      return;
    }
    stopSpeaking();
    mic.textContent = "Listening…";
    mic.setAttribute("aria-pressed", "true");
    device("voice", "listen-start");
    recognition.start();
  });
}

$("connect").addEventListener("click", () => {
  state.token = $("access-token").value.trim();
  act(async () => { await refresh(); storeToken(state.token); }, "Connected to the incident.").catch(() => {});
});
$("access-token").addEventListener("keydown", (event) => {
  if (event.key === "Enter") $("connect").click();
});
$("reset").addEventListener("click", () => act(async () => {
  forgetPurchase();
  await request("/demo/reset", "POST");
  Object.assign(state, {
    selectedPlanId: null, conversation: [], conversations: {}, selections: {}, stockFor: null,
    briefingPick: null, prefsShown: undefined,
  });
  hideMcpApp();
}, "Every synthetic incident was reset, and the saved preferences were cleared.").catch(() => {}));
$("pref-form").addEventListener("submit", (event) => {
  event.preventDefault();
  act(async () => {
    const raw = $("pref-cap").value.trim();
    const cap = Number(raw);
    if (raw && (!Number.isInteger(cap) || cap < 0)) throw new Error("Enter the spend cap as a whole number of dollars, or leave it empty.");
    await savePreferences({ rule: $("pref-rule").value, max_cost_usd: raw ? cap : null, note: $("pref-note").value.trim() });
  }, "Preferences saved for every incident. They steer the pick; they never approve a plan.").catch(() => {});
});
$("pref-clear").addEventListener("click", () => act(async () => {
  await request("/operator/preferences", "DELETE");
  state.prefsShown = undefined;
}, "Preferences cleared.").catch(() => {}));
$("banner-reset").addEventListener("click", () => act(async () => {
  forgetPurchase();
  await request("/demo/reset", "POST", { incident_id: state.incidentId });
  Object.assign(state, { selectedPlanId: null, conversation: [], stockFor: null });
  hideMcpApp();
}, "This incident was reset.").catch(() => {}));
window.addEventListener("hashchange", () => {
  const id = hashIncident();
  if (id !== state.incidentId) selectIncident(id).catch(() => {});
});
$("set-stock").addEventListener("click", () => act(async () => {
  const raw = $("stock-input").value.trim();
  const available = Number(raw);
  if (!raw || !Number.isInteger(available) || available < 0) throw new Error("Enter a whole number of units.");
  await request("/demo/inventory", "POST", { incident_id: state.incidentId, available });
  state.selectedPlanId = null;
}, "Stock changed. Earlier plans and approvals no longer apply.").then(checkAlerts).catch(() => {}));
$("link-account").addEventListener("click", () => { linkAccount().catch((error) => message(error.message || String(error))); });
$("sign-out").addEventListener("click", () => {
  signOut();
  message("Signed out. You're a guest: you can read and ask, but not act.", true);
});
$("alerts-bell").addEventListener("click", async () => {
  const alert = state.alerts.find((item) => item.incident_id !== state.incidentId);
  if (!alert || state.busy) return;
  await selectIncident(alert.incident_id).catch(() => {});
  if (state.incidentId === alert.incident_id) await announceAlert(alert);
});
$("ask-input").addEventListener("input", () => stopSpeaking());
$("ask-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = $("ask-input");
  const text = input.value;
  input.value = "";
  handleUtterance(text);
});
for (const chip of document.querySelectorAll(".chip")) {
  chip.addEventListener("click", () => handleUtterance(chip.dataset.say));
}
$("approve").addEventListener("click", () => act(
  () => approvePlan(state.snapshot.plans.find((item) => item.id === state.selectedPlanId)),
  "The selected plan was approved by the operator.",
).catch(() => {}));
$("execute").addEventListener("click", () => act(executeApproved, "Execution was operationally verified.").catch(() => {}));

device("mount");
setUpVoice();
renderConversation();
state.token = storedToken();
const resumed = readSession();
if (resumed) {
  state.session = resumed;
  state.token = resumed.access;
}
setInterval(() => { checkAlerts().catch(() => {}); }, 5000);
loadAuth().then(finishSignIn).catch(() => {}).then(() => act(refresh, "").catch(() => {})).then(() => {
  if (state.signInNote) say("assistant", state.signInNote);
  if (state.session) $("approver").value = state.session.username;
  loadVoice();
  recallMemory();
  checkAlerts().catch(() => {});
  const parked = storedPurchase();
  if (parked) {
    say("assistant", `A booking is waiting for “${parked.quote.plan_label}” on ${parked.incidentId} (${dollars(parked.quote.total_usd)}). `
      + "Say “resume” to hear the price again, or “no” to drop it. Nothing was charged.");
  }
}).catch(() => {});
