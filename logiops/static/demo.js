"use strict";

const $ = (id) => document.getElementById(id);
const DEFAULT_INCIDENT = "SHIP-421";
// Deep links: /demo#SHIP-433 opens that incident.
const hashIncident = () => decodeURIComponent(location.hash.slice(1)).trim().toUpperCase() || DEFAULT_INCIDENT;
const state = {
  token: "", snapshot: null, selectedPlanId: null, busy: false, conversation: [], speaking: false, app: null,
  awaitingExecute: false, pendingApproval: null, incidentId: hashIncident(), inbox: [], conversations: {}, selections: {}, stockFor: null,
  briefingPick: null, prefsShown: undefined,
};
const incidentPath = (suffix = "") => `/incidents/${encodeURIComponent(state.incidentId)}${suffix}`;
// MCP Apps host (protocol 2026-01-26). As the spec requires for web hosts, the view runs
// behind a sandbox proxy served from a different origin (127.0.0.1 <-> localhost locally,
// a second hostname in public mode). The view has no network and never sees the token;
// it can only ask the host to select a plan.
const MCP_APP = { uri: "ui://logiops/resolution-options.html", mime: "text/html;profile=mcp-app", protocol: "2026-01-26", proxyPath: "/mcp-app/sandbox.html" };
const SANDBOX_ORIGIN = (() => {
  const value = document.querySelector('meta[name="logiops-sandbox-origin"]')?.content || "";
  try {
    const url = new URL(value);
    return /^https?:$/.test(url.protocol) && url.origin !== location.origin ? url.origin : null;
  } catch (_) { return null; }  // no separate origin configured: fail closed, no MCP App
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
// The plan kinds a phrase can name, most specific first; the first one on screen wins.
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
  // Problems interrupt the screen reader; confirmations wait politely.
  box.setAttribute("role", success || !text ? "status" : "alert");
  box.setAttribute("aria-live", success || !text ? "polite" : "assertive");
}

function setBusy(busy) {
  state.busy = busy;
  renderControls();
}

// Say what to do next, not just what the server said.
function explainError(status, detail) {
  if (status === 401) {
    return state.token
      ? "That access token was not accepted. Copy it again from the testing instructions, paste it above, and press Connect."
      : "This public demo needs the access token from the testing instructions. Paste it above and press Connect.";
  }
  if (status === 429 && /agent/i.test(detail)) {
    return "That's the agent's per-minute question limit (each answer calls a paid model). Wait a minute and ask again; the plan panel and buttons still work.";
  }
  if (status === 429) return "Too many requests in the last minute. Wait a moment and try again.";
  return detail;
}

const TOKEN_KEY = "logiops-access-token";
function storedToken() {
  try { return sessionStorage.getItem(TOKEN_KEY) || ""; } catch (_) { return ""; }
}
function storeToken(token) {
  try { if (token) sessionStorage.setItem(TOKEN_KEY, token); else sessionStorage.removeItem(TOKEN_KEY); } catch (_) { /* Storage blocked: the token lasts until reload. */ }
}

async function request(path, method = "GET", body) {
  const headers = {};
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try { detail = (await response.json()).detail || detail; } catch (_) { /* HTTP error without JSON. */ }
    const error = new Error(explainError(response.status, detail));
    error.status = response.status;
    throw error;
  }
  return response.json();
}

async function mcpRequest(method, params) {
  const headers = { "Content-Type": "application/json", Accept: "application/json, text/event-stream" };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch("/mcp", {
    method: "POST", headers, cache: "no-store",
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
  });
  if (!response.ok) throw new Error(`MCP HTTP ${response.status}`);
  const body = await response.json();
  if (body.error) throw new Error(body.error.message || "MCP error");
  return body.result;
}

function loadAppResource() {
  // The view is static: read it once per page, not on every investigation (MCP budget).
  app.resource ??= (async () => {
    const listed = await mcpRequest("tools/list", {});
    const tool = listed.tools.find((item) => item.name === "investigate_incident");
    const uri = tool?._meta?.ui?.resourceUri ?? tool?._meta?.["ui/resourceUri"];
    if (uri !== MCP_APP.uri) return null;
    const read = await mcpRequest("resources/read", { uri });
    const content = read.contents?.[0];
    if (!content || content.mimeType !== MCP_APP.mime || typeof content.text !== "string") return null;
    const ui = content._meta?.ui || {};
    return { html: content.text, csp: ui.csp || {}, prefersBorder: ui.prefersBorder !== false };
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
  // A reset, stock change or newer investigation may have happened while loading.
  if (!resource || generation !== app.generation || !state.snapshot
      || String(step.input?.shipment_id || "").trim().toUpperCase() !== state.incidentId
      || step.output.source_version !== visibleVersion(state.snapshot)) return;
  await teardownMcpApp("replaced", { invalidate: false });
  if (generation !== app.generation) return;
  state.app = {
    incidentId: state.incidentId,
    version: step.output.source_version,
    input: step.input,
    result: { content: [{ type: "text", text: JSON.stringify(step.output) }], structuredContent: step.output },
    resource,
    ready: false,
  };
  const frame = document.createElement("iframe");
  frame.id = "mcp-app-frame";
  frame.title = "Resolution options (MCP App)";
  // The proxy needs both tokens (spec); its different origin is what isolates it from this page.
  frame.setAttribute("sandbox", "allow-scripts allow-same-origin");
  frame.setAttribute("referrerpolicy", "no-referrer");
  frame.src = `${SANDBOX_ORIGIN}${MCP_APP.proxyPath}?host=${encodeURIComponent(location.origin)}`;
  $("mcp-app-slot").replaceChildren(frame);
  $("mcp-app").classList.toggle("borderless", !resource.prefersBorder);
  $("mcp-app").hidden = false;
}

// The spec requires ui/resource-teardown before the view goes away; wait briefly for its answer.
function teardownMcpApp(reason, { invalidate = true } = {}) {
  const current = state.app;
  const frame = $("mcp-app-frame");
  state.app = null;
  if (invalidate) app.generation += 1;  // also cancels a view that is still loading
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

// When the card cannot be shown, say so (and why) instead of failing silently.
function showMcpAppNote(text) {
  const frame = $("mcp-app-frame");
  if (frame) frame.remove();
  const note = document.createElement("p");
  note.className = "mcp-app-note";
  note.textContent = text;
  $("mcp-app-slot").replaceChildren(note);
  $("mcp-app").hidden = false;
}

// Selection from the view is resolved against the host's own snapshot; labels, prices or
// versions sent by the iframe are never trusted, and nothing here can approve a plan.
function selectFromApp(params) {
  const text = params?.content?.type === "text" ? String(params.content.text) : "";
  const match = text.match(/^Select plan (\S+)$/);
  // Never change the selection under the operator while an action is running.
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
      hostContext: { theme: "dark", displayMode: "inline" },
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

// Critical orders first, then the worst delay, late units and cost (the server's default pick).
function rankKey(plan) {
  const critical = (plan.orders || []).filter((order) => order.priority === "critical").map((order) => order.delay_hours);
  return [Math.max(0, ...critical), plan.projected_customer_delay_hours, plan.late_units || 0, plan.incremental_cost_usd];
}
function byRank(a, b) {
  const left = rankKey(a), right = rankKey(b);
  return left.reduce((found, value, index) => found || value - right[index], 0);
}

// The plan the agent recommended: an exact plan ID in its answer, then a label,
// then the default ranking as a deterministic fallback.
function recommendedPlan(snapshot) {
  const plans = visiblePlans(snapshot);
  if (!plans.length) return null;
  const answer = latestAgentEvent(snapshot)?.data.answer || "";
  const id = window.LogiOpsIntent.recommendedPlanId(answer, plans);
  return plans.find((plan) => plan.id === id)
    || plans.find((plan) => answer.toLowerCase().includes(`recommend ${plan.label.toLowerCase()}`))
    || [...plans].sort(byRank)[0];
}

// Units per source across orders: "30 via delayed shipment", not one entry per order.
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
      // With two orders, say who is late and by how much.
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

// What the saved preferences point to, next to the agent's pick. Fixed rules, never an approval.
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
  // Refill the form only when the saved values change, never while someone is typing.
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

// Build the model's Markdown as DOM nodes; text always goes through textContent.
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
  // Answers sit under the panel's h2: their headings start at h3 and never skip a level.
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
      // Wide tables scroll inside a focusable region, so keyboard users can scroll them too.
      node = document.createElement("div");
      node.className = "table-scroll";
      node.tabIndex = 0;
      node.setAttribute("role", "region");
      node.setAttribute("aria-label", "Table from the agent's answer");
      const table = document.createElement("table");
      node.append(table);
      const head = table.createTHead().insertRow();
      for (const cell of block.head) {
        // An empty corner cell is not a column header.
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
    // Replies are Markdown; what the person typed stays literal text.
    const text = entry.role === "assistant" ? renderMarkdown(entry.text) : document.createElement("p");
    if (entry.role !== "assistant") text.textContent = entry.text;
    item.append(who, text);
    if (entry.meta) {
      const meta = document.createElement("small");
      meta.textContent = entry.meta;
      item.append(meta);
    }
    list.append(item);
  }
  list.scrollTop = list.scrollHeight;
}

// Proactive, and free: the first thing on screen is the state of the queue, from the inbox itself.
function welcomeText() {
  const open = state.inbox.filter((item) => item.status !== "verified");
  if (!state.inbox.length) {
    return `Hi, I'm LogiOps. Ask me what's happening with ${state.incidentId}, and I'll investigate it with the MCP tools.`;
  }
  const critical = open.filter((item) => item.priority === "critical").map((item) => item.incident_id);
  const queue = open.length
    ? `${open.length} open incident${open.length === 1 ? "" : "s"} in the inbox`
      + (critical.length ? `; ${critical.join(" and ")} ${critical.length === 1 ? "has a critical order" : "have critical orders"}` : "")
    : "Every incident in the inbox is resolved";
  return `Hi, I'm LogiOps. ${queue}. Ask “any delays today?” for my briefing, or ask what's happening with ${state.incidentId}.`;
}

// Read aloud the short spoken line when there is one, as a voice assistant would.
function say(role, text, meta, spoken) {
  state.conversation.push({ role, text, meta });
  renderConversation();
  if (role === "assistant" && $("speak-replies").checked && "speechSynthesis" in window) {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(spoken || window.LogiOpsMarkdown.plainText(text));
    utterance.lang = "en-US";
    window.speechSynthesis.speak(utterance);
  }
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
  // Name the plan on the button, so a selection made elsewhere (the MCP App) is visible.
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
  // The view shows the plans of one incident and data version; hide it once they are gone.
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
    // A useful default per incident: one unit less than on hand.
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
    state.conversation.push({ role: "assistant", text: agentEvent.data.answer, meta: traceSummary(agentEvent.data) });
  }
  renderConversation();
  renderPreferenceLine(snapshot);
  renderPreferences(snapshot);
  renderPlans(snapshot);
  renderTimeline(snapshot.events);
  const execution = snapshot.executions[0];
  $("execution-state").textContent = execution ? "Operationally verified" : visibleApproval(snapshot) ? "Approved · ready" : "Waiting for approval";
  $("execution-result").hidden = !execution;
  // Whoever executed last, the next visitor sees why there is nothing left to approve.
  $("state-banner").hidden = !execution;
  if (execution) {
    const plan = snapshot.plans.find((item) => item.id === execution.plan_id);
    $("state-banner-text").textContent = `${incident.incident_id} was already executed with “${plan?.label || execution.plan_id}” and verified. Questions now refer to that result; reset this incident to run the whole flow again.`;
  }
  if (execution) {
    $("execution-result").textContent = executionSummary(snapshot, execution);
  }
  renderControls();
}

function traceSummary(run) {
  const tokens = (run.usage?.inputTokens || 0) + (run.usage?.outputTokens || 0);
  return `${run.tool_trace.length} MCP calls · ${run.mode} mode · ${tokens} tokens${run.truncated ? " · truncated" : ""}`;
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

// Each incident keeps its own conversation and selection while you look at another.
async function selectIncident(id) {
  if (state.busy || id === state.incidentId) return;
  state.conversations[state.incidentId] = state.conversation;
  state.selections[state.incidentId] = state.selectedPlanId;
  state.incidentId = id;
  state.conversation = state.conversations[id] || [];
  state.selectedPlanId = state.selections[id] || null;
  state.awaitingExecute = false;
  state.pendingApproval = null;
  history.replaceState(null, "", `#${encodeURIComponent(id)}`);
  hideMcpApp("incident changed");
  await act(refresh, "");
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
    if (error.status === 401) {
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

// The plan kinds a sentence names ("the split plan"), or null when it names none.
function namedPlanKinds(text) {
  const found = planKeywords.find(([, pattern]) => pattern.test(text));
  return found ? found[0] : null;
}

function planFromUtterance(text) {
  const plans = visiblePlans(state.snapshot);
  const preferred = state.snapshot.preference && plans.find((plan) => plan.id === state.snapshot.preference.preferred_plan_id);
  if (preferred && /\b(?:preferred|my preference)\b/.test(text)) return preferred;
  // "The cheapest plan" and "the $240 plan" name a plan by its price.
  const selector = window.LogiOpsIntent.planSelector(text);
  if (selector.cheapest) {
    return [...plans].sort((a, b) => a.incremental_cost_usd - b.incremental_cost_usd || byRank(a, b))[0] || null;
  }
  if (selector.cost !== undefined) {
    const priced = plans.filter((plan) => plan.incremental_cost_usd === selector.cost);
    return priced.length === 1 ? priced[0] : null;
  }
  const kinds = namedPlanKinds(text);
  // A named plan that the current data does not offer is not silently replaced.
  if (kinds) return kinds.map((kind) => plans.find((plan) => plan.kind === kind)).find(Boolean) || null;
  return recommendedPlan(state.snapshot);
}

// What an approval commits to, read back before it acts: price, delay, and any critical order left late.
function approvalReadback(plan) {
  const delay = plan.projected_customer_delay_hours ? `${plan.projected_customer_delay_hours} hours of delay` : "no delay";
  const late = (plan.orders || []).filter((order) => order.priority === "critical" && order.delay_hours > 0);
  const warning = late.length ? `, and it leaves the critical order for ${late.map((order) => order.customer).join(" and ")} late` : "";
  return `Approve “${plan.label}” for $${plan.incremental_cost_usd} extra, ${delay}${warning}?`;
}

// A thin intent layer, like an Alexa+ action: approval and execution go through the
// same REST endpoints as the buttons; anything else is a question for the agent.
// Commands must be the whole utterance (intent.js): "Should we approve the split plan?"
// asks, and "Please do not execute it yet" never executes.

async function handleUtterance(raw) {
  const text = raw.trim();
  if (!text || state.busy) return;
  // "What about SHIP-452?" moves to that incident first; the question then goes there.
  const mentioned = window.LogiOpsIntent.mentionedIncident(text, state.inbox.map((item) => item.incident_id));
  if (mentioned && mentioned !== state.incidentId) {
    await selectIncident(mentioned).catch(() => {});
    if (state.incidentId !== mentioned) return;
  }
  say("user", text);
  const lower = text.toLowerCase();
  // A read-back approval waits for the very next utterance; anything else cancels it.
  const pending = state.pendingApproval;
  state.pendingApproval = null;
  // Preferences and briefings first: "reset my preferences" must not reset the incident.
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
      say("assistant", run.answer, `briefing · ${traceSummary(run)}`, run.spoken);
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
    command = null;  // "show me the options" is a question for the agent
  }
  // A bare "yes" only confirms the execution offered in the previous reply.
  const awaitingExecute = state.awaitingExecute;
  state.awaitingExecute = false;
  try {
    if (command === "reset") {
      const id = state.incidentId;
      await act(() => request("/demo/reset", "POST", { incident_id: id }), "");
      state.selectedPlanId = null;
      state.conversation = [];
      hideMcpApp();
      say("assistant", `Done. ${id} is back to its original state.`);
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
      // Speech can mishear a plan, so a spoken approval is read back and waits for a yes.
      state.pendingApproval = { planId: plan.id, sourceVersion: plan.source_version };
      say("assistant", `${approvalReadback(plan)} Say “yes” to approve it, or ask me anything else.`);
    } else if (command === "confirm" && pending) {
      const plan = visiblePlans(state.snapshot)
        .find((item) => item.id === pending.planId && item.source_version === pending.sourceVersion);
      if (!plan) {
        say("assistant", "The data changed after I read that plan back, so nothing was approved. Ask me again.");
        return;
      }
      await act(() => approvePlan(plan), "");
      say("assistant", `Approved “${plan.label}” for version ${plan.source_version}. Say “execute it” when you're ready.`);
      state.awaitingExecute = true;
    } else if (command === "execute" || (command === "confirm" && awaitingExecute && visibleApproval(state.snapshot))) {
      // "Execute the reroute" while another plan is approved must not run the approved one.
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
    } else {
      // Follow-ups reuse the latest investigation of the data on screen; anything that
      // asks to (re)investigate, or arrives after the data changed, runs a fresh one.
      // An executed incident cannot be re-planned, so its questions are always follow-ups.
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
      say("assistant", run.answer, `${fresh ? "investigation" : "follow-up"} · ${traceSummary(run)}`, run.spoken);
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
  });
  recognition.addEventListener("error", (event) => {
    if (event.error !== "no-speech" && event.error !== "aborted") message(`Voice input unavailable: ${event.error}`);
  });
  mic.addEventListener("click", () => {
    if (mic.getAttribute("aria-pressed") === "true") {
      recognition.stop();
      return;
    }
    mic.textContent = "Listening…";
    mic.setAttribute("aria-pressed", "true");
    recognition.start();
  });
}

$("connect").addEventListener("click", () => {
  state.token = $("access-token").value.trim();
  // Kept for this tab only, so a reload does not ask again; closing the tab forgets it.
  act(async () => { await refresh(); storeToken(state.token); }, "Connected to the incident.").catch(() => {});
});
$("access-token").addEventListener("keydown", (event) => {
  if (event.key === "Enter") $("connect").click();
});
$("reset").addEventListener("click", () => act(async () => {
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
  // Number("2.5") is not an integer; parseInt would have quietly sent 2.
  if (!raw || !Number.isInteger(available) || available < 0) throw new Error("Enter a whole number of units.");
  await request("/demo/inventory", "POST", { incident_id: state.incidentId, available });
  state.selectedPlanId = null;
}, "Stock changed. Earlier plans and approvals no longer apply; ask the agent again.").catch(() => {}));
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

setUpVoice();
renderConversation();
state.token = storedToken();
act(refresh, "").catch(() => {});
