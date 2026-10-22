"use strict";

import { createApi, createStorage, explainError as explain } from "./app/api.js";
import { createVoice } from "./app/voice.js";
import { createMemory } from "./app/memory.js";
import { describePreferences, mergedPreferences, preferenceLine, preferenceEffect as effectOf } from "./app/preferences.js";
import { createPurchase, dollars, bookingRows } from "./app/purchase.js";
import { createAlerts, bellText } from "./app/alerts.js";
import { recordedNote } from "./app/approval.js";
import { createCommands } from "./app/commands.js";
import { createStore } from "./app/store.js";
import {
  EVENT_LABELS, formatDate, visibleVersion, visibleApproval, visiblePlans, latestAgentEvent, byRank,
  localWarehouse, namedPlanKinds, distinguishing, money, recommendedPlan as pickRecommended, planFromUtterance as pickFromUtterance,
} from "./app/selectors.js";
import { welcomeText as greeting } from "./app/greeting.js";
import { checkBadge, checkNote, fallbackNote, traceSummary, executionSummary } from "./app/run-badges.js";
import { renderMarkdown } from "./app/markdown-dom.js";
import { sessionFigures } from "./app/metrics.js";
import { drawField } from "./app/field-dom.js";
import { createStartup } from "./app/startup.js";
import { createFocusKeeper, loadAuthInto, openHtml, parkedPurchaseLine, showMessage } from "./app/page.js";
import { drawMap, drawBars, stepLabel } from "./device/render.js";
import { displayPlan } from "./device/surfaces.js";

const $ = (id) => document.getElementById(id);
const DEFAULT_INCIDENT = "SHIP-421";
const hashIncident = () => decodeURIComponent(location.hash.slice(1)).trim().toUpperCase() || DEFAULT_INCIDENT;
const store = createStore({
  token: "", snapshot: null, selectedPlanId: null, busy: false, conversation: [], speaking: false,
  awaitingExecute: false, pendingApproval: null, incidentId: hashIncident(), inbox: [], conversations: {}, selections: {}, stockFor: null,
  briefingPick: null, prefsShown: undefined, cardTheme: "dark",
  voice: { engine: "browser", voice: null, fillers: [] }, speechTurn: 0, auth: { enabled: false }, session: null,
  memoryIncident: null,
});
const state = store.state;
const incidentPath = (suffix = "") => `/incidents/${encodeURIComponent(state.incidentId)}${suffix}`;
function message(text, success = false) {
  showMessage($("message"), text, success);
}

const NEXT_FOCUS = { approve: "execute", execute: "banner-reset", "banner-reset": "ask-input" };
const focus = createFocusKeeper({ fallback: (before) => (before?.id && NEXT_FOCUS[before.id] ? $(NEXT_FOCUS[before.id]) : null) });

function setBusy(busy) {
  if (busy && !state.busy) focus.remember();
  store.set({ busy });
  renderControls();
  if (!busy) focus.restore();
}

function explainError(status, detail) {
  return explain(status, detail, { authEnabled: state.auth.enabled, signedIn: Boolean(state.session), hasToken: Boolean(state.token) });
}

const api = createApi({
  storage: createStorage(), origin: location.origin,
  credentials: () => ({ token: state.token, session: state.session, auth: state.auth }),
  onSession: (session) => {
    state.session = session;
    state.token = session ? session.access : api.storedToken();
    lockApprover(session);
    renderAccount();
  },
  onAgentCall: (phase) => {
    if (phase === "request") {
      startFiller();
      return;
    }
    voice.cancelFiller();
  },
});
const { request, storedToken, storeToken, readSession, keepSession, signOut, randomText } = api;

const purchase = createPurchase({
  storage: createStorage(), request, crypto: window.crypto,
  api: { token: () => state.token, fetch: (...args) => fetch(...args), explain: explainError },
  selectors: { visiblePlans, visibleApproval, namedPlanKinds, planFromUtterance: (text) => planFromUtterance(text) },
  snapshot: () => state.snapshot, incidentId: () => state.incidentId,
  say: (...args) => say(...args), act: (...args) => act(...args), approvePlan: (plan) => approvePlan(plan),
  onBooking: (booking) => showBooking(booking),
});
const storedPurchase = () => purchase.stored();
const forgetPurchase = () => purchase.forget();

const alerts = createAlerts({
  request, acknowledge: false, storage: createStorage(), incidentId: () => state.incidentId, isBusy: () => state.busy, isHidden: () => document.hidden,
  onAlerts: () => renderAlertBell(),
  onAnnounce: async (alert) => {
    state.pendingApproval = null;
    state.awaitingExecute = false;
    if (purchase.pending()?.incidentId === alert.incident_id || storedPurchase()?.incidentId === alert.incident_id) forgetPurchase();
    state.selectedPlanId = alert.new_plan?.plan_id || null;
    await refresh().catch(() => {});
    say("assistant", alert.message, alert.approval_invalidated ? "proactive alert · approval invalidated" : "proactive alert · nothing approved", alert.spoken);
  },
});
const checkAlerts = () => alerts.check();

function renderAccount() {
  const box = $("account");
  const name = state.session?.username || "";
  box.hidden = !state.auth.enabled;
  box.classList.toggle("signed-in", Boolean(state.session));
  $("account-status").textContent = state.session ? `Signed in as ${name}` : "Guest · read only";
  $("link-account").hidden = Boolean(state.session);
  $("account-menu").hidden = !state.session;
  if (!state.session) $("account-menu").open = false;
  $("account-name").textContent = name;
  document.querySelector("#account-menu .avatar").textContent = name.slice(0, 1);
  $("account-detail").textContent = `Signed in as ${name}. You can approve, execute and book.`;
}
function loadAuth() {
  return loadAuthInto({ api, state, keepSession, renderAccount });
}
async function linkAccount() {
  if (!state.auth.enabled) {
    say("assistant", "Sign-in isn't set up on this server, so the demo already acts as the operator.");
    return;
  }
  const url = await api.beginSignIn({ hash: location.hash, returnTo: "/console" });
  if (!url) {
    say("assistant", "This browser blocks session storage, so I can't sign you in here.");
    return;
  }
  location.assign(url);
}

function recommendedPlan(snapshot) {
  return pickRecommended(snapshot, window.LogiOpsIntent);
}

function renderPlans(snapshot) {
  const container = $("plans");
  const hadFocus = container.contains(document.activeElement);
  container.replaceChildren();
  container.setAttribute("role", "radiogroup");
  container.setAttribute("aria-label", "Resolution plans");
  const plans = visiblePlans(snapshot);
  const cell = (className, text) => {
    const node = document.createElement("span");
    node.className = className;
    node.textContent = text;
    return node;
  };
  if (!plans.length) {
    drawField($("plans-field"), [], null, { shapes: window.LogiOpsField });
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "Ask LogiOps to investigate to see the options.";
    container.append(empty);
    return;
  }
  const approval = visibleApproval(snapshot);
  const executedId = snapshot.executions[0]?.plan_id;
  const recommended = recommendedPlan(snapshot);
  if (approval) {
    state.selectedPlanId = approval.plan_id;
  } else if (!plans.some((plan) => plan.id === state.selectedPlanId)) {
    state.selectedPlanId = recommended?.id || plans[0].id;
  }
  drawField($("plans-field"), plans, state.selectedPlanId, { shapes: window.LogiOpsField, id: "plans-field" });
  const orders = plans[0].orders || [];
  const columns = orders.length && orders.length <= 3 ? orders : null;
  container.style.setProperty("--orders", String(columns ? columns.length : 1));
  const head = document.createElement("div");
  head.className = "plan-head";
  head.setAttribute("aria-hidden", "true");
  head.append(cell("", ""), cell("", "Plan"));
  for (const order of columns || [{ customer: "Delay" }]) {
    const name = cell("order-head", order.customer);
    if (order.priority === "critical") name.prepend(cell("critical-tag", "Critical"));
    head.append(name);
  }
  head.append(cell("", "Extra"));
  container.append(head);
  const outcome = (hours, who) => {
    const node = cell(`outcome${hours ? " late" : ""}`, hours ? `+${hours} h` : "On time");
    if (who) node.prepend(cell("visually-hidden", `${who}: `));
    return node;
  };
  const labels = plans.map((plan) => plan.label);
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
      renderJourney(snapshot);
      renderControls();
    });
    if (hadFocus && radio.checked) queueMicrotask(() => radio.focus({ preventScroll: true }));
    const title = document.createElement("strong");
    distinguishing(plan.label, labels).forEach(([text, marked], index) => {
      const space = index ? " " : "";
      if (!marked) {
        title.append(`${space}${text}`);
        return;
      }
      const mark = document.createElement("span");
      mark.className = "diff";
      mark.textContent = text;
      title.append(...[space, mark].filter(Boolean));
    });
    const badges = [];
    if (executedId === plan.id) badges.push(["Executed", "badge done"]);
    else if (approval?.plan_id === plan.id) badges.push(["Approved", "badge done"]);
    if (isRecommended) badges.push(["Agent pick", "badge"]);
    if (plan.id === snapshot.preference?.preferred_plan_id) badges.push(["Your preference", "badge preference"]);
    for (const [text, className] of badges) title.append(cell(className, text));
    card.append(radio, title);
    if (columns) {
      for (const column of columns) {
        const order = (plan.orders || []).find((item) => item.order_id === column.order_id);
        card.append(outcome(order?.delay_hours || 0, column.customer));
      }
    } else {
      card.append(outcome(plan.projected_customer_delay_hours, "Delay"));
    }
    const cost = cell("plan-value", money(plan.incremental_cost_usd));
    cost.prepend(cell("visually-hidden", "Extra: "));
    card.append(cost);
    container.append(card);
  }
}

function renderPreferenceLine(snapshot) {
  const line = $("preference-line");
  const preference = snapshot.preference;
  line.hidden = !preference;
  if (!preference) return;
  const strong = document.createElement("strong");
  const described = preferenceLine(preference);
  strong.textContent = described.lead;
  line.replaceChildren(strong, document.createTextNode(described.text));
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
  await request("/operator/preferences", "PUT", mergedPreferences(state.snapshot?.operator_preferences, update));
  state.prefsShown = undefined;
}

function preferenceEffect() {
  return effectOf(state.snapshot, state.incidentId);
}

function renderTimeline(events) {
  const timeline = $("timeline");
  timeline.replaceChildren();
  for (const event of [...events].reverse()) {
    const item = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = EVENT_LABELS[event.name] || event.name.replaceAll("_", " ");
    const when = document.createElement("small");
    when.textContent = formatDate(event.recorded_at);
    item.append(title, when);
    timeline.append(item);
  }
  $("event-count").textContent = `${events.length} event${events.length === 1 ? "" : "s"}`;
}

function renderConversation() {
  const list = $("conversation");
  list.replaceChildren();
  const entries = state.conversation.length ? state.conversation : [{ role: "assistant", text: welcomeText() }];
  for (const entry of entries) {
    const item = document.createElement("li");
    const note = String(entry.meta || "").startsWith("welcome back");
    item.className = `turn ${entry.role}${note ? " note" : ""}`;
    const who = document.createElement("span");
    who.className = "turn-role";
    who.textContent = entry.role === "user" ? "You" : "LogiOps";
    item.append(who);
    if (entry.role !== "assistant") {
      const text = document.createElement("p");
      text.textContent = entry.text;
      item.append(text);
    } else if (entry.text.length > 280 && !note) {
      const lead = document.createElement("p");
      lead.className = "spoken";
      lead.textContent = entry.spoken || leadSentence(entry.text);
      const full = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "Full answer";
      full.append(summary, renderMarkdown(entry.text));
      item.append(lead, full);
    } else {
      item.append(renderMarkdown(entry.text));
    }
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
  if (list.scrollHeight > list.clientHeight) list.scrollTop = list.scrollHeight;
}

function leadSentence(text) {
  const plain = window.LogiOpsMarkdown.plainText(text).replace(/\s+/g, " ").trim();
  const first = plain.match(/^.{20,200}?[.!?](?=\s|$)/);
  return first ? first[0] : `${plain.slice(0, 180).trim()}…`;
}

const stations = {
  live: false,
  steps: [],
  start() {
    this.live = true;
    this.steps = [];
    paintStations([], { waiting: true });
  },
  step(step, kind) {
    if (kind === "restart") this.steps = [];
    else this.steps.push(step);
    paintStations(this.steps, { waiting: true, fresh: true });
  },
  stop() {
    this.live = false;
  },
};

function renderStations(run) {
  paintStations(run?.tool_trace || [], { check: run ? checkBadge(run) : null });
}

function paintStations(steps, { waiting = false, check = null, fresh = false } = {}) {
  const list = $("agent-steps");
  list.replaceChildren();
  const station = (className, label, detail) => {
    const item = document.createElement("li");
    if (className) item.className = className;
    const name = document.createElement("b");
    name.textContent = label;
    item.append(name);
    if (detail) {
      const small = document.createElement("span");
      small.textContent = detail;
      item.append(small);
    }
    list.append(item);
  };
  steps.forEach((step, index) => {
    const last = fresh && index === steps.length - 1;
    station([step.is_error ? "error" : "", last ? "fresh" : ""].filter(Boolean).join(" "), stepLabel(step).replace(/ · (\d+) (?:quotes|plans|incidents)\b/, " · $1"), step.tool);
  });
  if (waiting) station("waiting", steps.length ? "Working" : "Reading the incident", null);
  else if (check && steps.length) station(`check${check.passed ? "" : " failed"}`, check.text, null);
}

function renderJourney(snapshot) {
  const plan = displayPlan(snapshot, state.selectedPlanId, recommendedPlan(snapshot));
  const marks = { route: window.LogiOpsRoute, journey: window.LogiOpsJourney };
  drawMap($("console-map-svg"), $("console-map-caption"), snapshot, plan, { ...marks, id: "console-map" });
  drawBars($("console-bars"), plan, marks, snapshot.state.shipment, document, snapshot.state.orders);
}

function welcomeText() {
  return greeting({ inbox: state.inbox, incidentId: state.incidentId });
}

const memory = createMemory({
  storage: createStorage(), request, randomText,
  credentials: () => ({ token: state.token, session: state.session, auth: state.auth }),
  incident: () => state.incidentId,
});
const memorySession = () => memory.session();
const remember = (role, text) => memory.remember(role, text);

async function recallMemory() {
  const recalled = await memory.recall();
  if (!recalled) return;
  state.memoryIncident = recalled.last_incident || null;
  if (recalled.welcome && !state.conversation.some((turn) => turn.role === "user" || String(turn.meta || "").startsWith("welcome back"))) {
    say("assistant", recalled.welcome, "welcome back · from memory", recalled.welcome);
  }
}

function say(role, text, meta, spoken, check) {
  state.conversation.push({ role, text, meta, check, spoken });
  renderConversation();
  if (!state.forgetting && !String(meta || "").startsWith("welcome back")) remember(role, role === "assistant" ? (spoken || window.LogiOpsMarkdown.plainText(text)) : text);
  if (role !== "assistant") return;
  if (speechOn()) speak(spoken || window.LogiOpsMarkdown.plainText(text));
}

function speechOn() {
  return $("speak-replies").checked && (state.voice.engine === "polly" || "speechSynthesis" in window);
}

const voice = createVoice({ getToken: () => state.token, getConfig: () => state.voice, isEnabled: speechOn });
const stopSpeaking = (options) => voice.stop(options);
const speak = (line, options) => voice.speak(line, options);
const startFiller = () => voice.startFiller();

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
  $("approve").textContent = selected && selected.id === recommendedPlan(snapshot)?.id ? "Approve the pick" : "Approve selected plan";
  $("execute").disabled = state.busy || !approved || executed;
  $("reset").disabled = state.busy;
  $("banner-reset").disabled = state.busy;
  $("set-stock").disabled = state.busy || !snapshot || executed || !localWarehouse(snapshot);
  for (const id of ["pref-rule", "pref-cap", "pref-note", "pref-save", "pref-clear"]) $(id).disabled = state.busy || !snapshot;
  $("import-pack").disabled = state.busy;
  $("stock-input").disabled = state.busy || !snapshot || !localWarehouse(snapshot);
  $("connect").disabled = state.busy;
  $("retry").disabled = state.busy;
}

function renderInbox() {
  const list = $("inbox");
  const focused = list.contains(document.activeElement) ? document.activeElement.dataset.incident : null;
  const longestDelay = Math.max(1, ...state.inbox.map((item) => item.delay_hours || 0));
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
    card.dataset.incident = item.incident_id;
    card.setAttribute("aria-pressed", String(item.incident_id === state.incidentId));
    const done = item.status === "executed";
    card.classList.toggle("done", done);
    const top = tag("incident-top", "");
    top.append(tag("incident-id", item.incident_id));
    if (item.critical_units_at_risk > 0) {
      const risk = tag("at-risk", `${item.critical_units_at_risk} critical`);
      risk.append(tag("visually-hidden", " units at risk"));
      top.append(risk);
    } else if (item.priority === "critical") {
      top.append(tag("critical", "Critical order"));
    }
    const trail = tag("mini", "");
    trail.style.setProperty("--delay", `${Math.round((item.delay_hours || 0) / longestDelay * 48)}%`);
    trail.setAttribute("aria-hidden", "true");
    const delayLabel = document.createElement("b");
    delayLabel.textContent = `+${item.delay_hours || 0} h`;
    trail.append(document.createElement("i"), delayLabel);
    const foot = tag("incident-foot", "");
    foot.append(trail);
    if (item.incident_id === state.briefingPick) foot.append(tag("start-here", "Start here"));
    else if (item.status !== "detected") foot.append(tag("state", item.status));
    card.append(top, tag("incident-text", `${item.kind_label} · ${item.route.split("→").pop().trim()}`), foot);
    card.addEventListener("click", () => selectIncident(item.incident_id).catch(() => {}));
    entry.append(card);
    list.append(entry);
    if (focused === item.incident_id) card.focus({ preventScroll: true });
  }
}

function render(snapshot) {
  state.snapshot = snapshot;
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
  $("incident-status").textContent = incident.status[0].toUpperCase() + incident.status.slice(1);
  $("promise-label").textContent = incident.orders.length === 1 ? "Customer promise" : "Original ETA";
  const warehouse = localWarehouse(snapshot);
  $("stock-value").textContent = warehouse ? `${incident.inventory[warehouse].available} units` : "None";
  $("stock-label").textContent = warehouse ? `Stock at ${warehouse[0].toUpperCase()}${warehouse.slice(1)}` : "Local stock";
  $("stock-scope").textContent = warehouse ? `(${warehouse[0].toUpperCase()}${warehouse.slice(1)} warehouse; invalidates approvals)` : "(this incident has no local warehouse)";
  if (state.stockFor !== incident.incident_id) {
    state.stockFor = incident.incident_id;
    $("stock-input").max = String(units);
    $("stock-input").value = warehouse ? String(Math.max(0, incident.inventory[warehouse].available - 1)) : "";
  }
  $("chip-status").dataset.say = `What's happening with shipment ${incident.incident_id}, and which plan should we choose?`;
  $("chip-status").textContent = `Status of ${incident.incident_id}`;
  $("original-eta").textContent = formatDate(shipment.original_eta);
  $("delayed-eta").textContent = formatDate(shipment.delayed_eta);
  const delay = Math.round((new Date(shipment.delayed_eta) - new Date(shipment.original_eta)) / 3600000);
  $("delay-hours").textContent = `+${delay} h`;
  const agentEvent = latestAgentEvent(snapshot);
  const mode = agentEvent?.data.mode;
  $("agent-mode").textContent = mode === "bedrock" ? "Live · Amazon Bedrock" : mode === "replay" ? "Replay · scripted model" : mode || "Ready";
  $("agent-mode").classList.toggle("live", mode === "bedrock");
  if (!state.conversation.length && agentEvent) {
    state.conversation.push({
      role: "assistant", text: agentEvent.data.display_answer || agentEvent.data.answer, meta: traceSummary(agentEvent.data), check: checkBadge(agentEvent.data),
      spoken: agentEvent.data.spoken,
    });
  }
  if (!stations.live) renderStations(agentEvent?.data || null);
  renderJourney(snapshot);
  renderConversation();
  renderPreferenceLine(snapshot);
  renderPreferences(snapshot);
  renderPlans(snapshot);
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

function noteCheck(run) {
  const note = checkNote(run);
  if (note) message(note);
}

function noteFallback(run) {
  const note = fallbackNote(run);
  if (note) message(note, true);
}

async function refresh() {
  state.inbox = (await request("/incidents")).incidents;
  if (!state.inbox.some((item) => item.incident_id === state.incidentId)) {
    state.incidentId = state.inbox[0]?.incident_id || DEFAULT_INCIDENT;
    history.replaceState(null, "", `#${encodeURIComponent(state.incidentId)}`);
  }
  render(await request(incidentPath()));
  loadMetrics().catch(() => {});
}

async function loadMetrics() {
  const metrics = await request("/metrics");
  const box = $("metrics");
  const figures = sessionFigures(metrics.session, { always: true });
  box.replaceChildren();
  for (const [value, label] of figures) {
    const item = document.createElement("li");
    const figure = document.createElement("strong");
    figure.textContent = value;
    const caption = document.createElement("span");
    caption.textContent = label;
    item.append(figure, " ", caption);
    box.append(item);
  }
  box.hidden = false;
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
  purchase.take();
  history.replaceState(null, "", `#${encodeURIComponent(id)}`);
  try {
    await act(async () => {}, "");
  } catch (error) {
    if (state.snapshot && state.snapshot.state.incident_id !== id) {
      state.incidentId = state.snapshot.state.incident_id;
      state.conversation = state.conversations[state.incidentId] || [];
      state.selectedPlanId = state.selections[state.incidentId] || null;
      history.replaceState(null, "", `#${encodeURIComponent(state.incidentId)}`);
      render(state.snapshot);
    }
    throw error;
  }
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
      $("developer").open = true;
      $("access-token").focus();
    } else if (error.status === 0) {
      $("connection").textContent = "Offline";
      $("connection").className = "connection error";
    }
    throw error;
  } finally { setBusy(false); }
}

function lockApprover(session) {
  $("approver").readOnly = Boolean(session);
  if (session) $("approver").value = session.username;
}

async function approvePlan(plan) {
  const approvedBy = $("approver").value.trim();
  if (!plan || !approvedBy) throw new Error("Select a plan and enter an approver name.");
  const approval = await request(incidentPath("/approvals"), "POST", {
    plan_id: plan.id, source_version: plan.source_version, approved_by: approvedBy,
  });
  const note = recordedNote(approvedBy, approval);
  if (note) {
    $("approver").value = approval.approved_by;
    say("assistant", note, "audit · who approved");
  }
}

async function executeApproved() {
  const approval = visibleApproval(state.snapshot);
  if (!approval) throw new Error("No plan is approved for the current incident version.");
  await request(incidentPath("/execute"), "POST", {
    plan_id: approval.plan_id, source_version: approval.source_version,
  });
}

function planFromUtterance(text) {
  return pickFromUtterance(text, state.snapshot, window.LogiOpsIntent);
}

function showBooking(booking) {
  const box = $("booking");
  if (!booking) {
    box.hidden = true;
    box.replaceChildren();
    return;
  }
  const head = document.createElement("p");
  head.className = "booking-head";
  head.textContent = `Booked ${booking.number} · ${dollars(booking.total_usd)} charged once (simulated payment)`;
  const list = document.createElement("dl");
  list.className = "booking-lines";
  for (const [term, value, kind] of bookingRows(booking)) {
    const dt = document.createElement("dt");
    dt.textContent = term;
    const dd = document.createElement("dd");
    dd.textContent = value;
    if (kind === "line") dt.className = dd.className = "line";
    list.append(dt, dd);
  }
  const open = document.createElement("button");
  open.type = "button";
  open.className = "secondary";
  open.textContent = "Open printable receipt";
  open.addEventListener("click", () => openReceipt(booking.number).catch((error) => message(error.message || String(error))));
  box.replaceChildren(head, list, open);
  box.hidden = false;
}

async function openReceipt(number) {
  openHtml(await purchase.openReceipt(number));
}

function renderAlertBell() {
  const bell = $("alerts-bell");
  const shown = bellText(alerts.current(), state.incidentId);
  bell.hidden = !shown;
  bell.textContent = shown ? shown.text : "";
  bell.setAttribute("aria-label", shown ? shown.label : "No proactive alerts");
}

const commands = createCommands({
  store, intent: window.LogiOpsIntent, request, purchase,
  selectors: { visiblePlans, visibleApproval, namedPlanKinds, latestAgentEvent, visibleVersion, planFromUtterance: (text) => planFromUtterance(text) },
  badges: { checkBadge, traceSummary, executionSummary, noteCheck, noteFallback },
  preferences: { describe: describePreferences, effect: effectOf },
  say, act, stopSpeaking, selectIncident, onInbox: () => renderInbox(),
  approvePlan, executeApproved, savePreferences, linkAccount, signOut,
  investigate: (path, body) => {
    stations.start();
    return api.streamed(`${path}/stream`, body, (step, kind) => stations.step(step, kind)).finally(() => stations.stop());
  },
});

function handleUtterance(raw) {
  return commands.handle(raw);
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
    stopSpeaking();
    mic.textContent = "Listening…";
    mic.setAttribute("aria-pressed", "true");
    recognition.start();
  });
}

$("connect").addEventListener("click", () => {
  state.token = $("access-token").value.trim();
  act(async () => { storeToken(state.token); }, "Connected to the incident.").then(() => {
    $("retry").hidden = true;
    afterConnected();
  }).catch(() => {});
});
$("access-token").addEventListener("keydown", (event) => {
  if (event.key === "Enter") $("connect").click();
});
$("reset").addEventListener("click", () => act(async () => {
  forgetPurchase();
  await request("/demo/reset", "POST");
  store.set({
    selectedPlanId: null, conversation: [], conversations: {}, selections: {}, stockFor: null,
    briefingPick: null, prefsShown: undefined,
  });
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
  store.set({ selectedPlanId: null, conversation: [], stockFor: null });
}, "This incident was reset.").catch(() => {}));
window.addEventListener("hashchange", () => {
  const id = hashIncident();
  if (id !== state.incidentId) selectIncident(id).catch(() => {});
});
function packResult(text, failed = false) {
  const box = $("pack-result");
  box.textContent = text;
  box.classList.toggle("failed", failed);
}

async function importPack(file) {
  let pack;
  try {
    pack = JSON.parse(await file.text());
  } catch (_) {
    const text = "That file is not JSON. Start from the built-in incidents (JSON) below and keep the same shape.";
    packResult(text, true);
    throw new Error(text);
  }
  try {
    const result = await request("/scenario/packs", "POST", pack);
    packResult(`Registered ${result.registered.join(", ")}: ${result.incidents.length} incidents in the inbox until the server restarts.`);
    return result;
  } catch (error) {
    const problems = error.detail?.errors;
    if (Array.isArray(problems) && problems.length) {
      packResult(`Nothing was registered. ${problems.slice(0, 3).map((item) => `${item.incident} ${item.path}: ${item.message}`).join(" · ")}${problems.length > 3 ? ` · and ${problems.length - 3} more` : ""}`, true);
    } else {
      packResult(error.message || String(error), true);
    }
    throw error;
  }
}

$("import-pack").addEventListener("click", () => {
  const file = $("pack-file").files?.[0];
  if (!file) {
    packResult("Choose a JSON scenario pack first.", true);
    return;
  }
  act(() => importPack(file), "").catch(() => {});
});
$("set-stock").addEventListener("click", () => act(async () => {
  const raw = $("stock-input").value.trim();
  const available = Number(raw);
  if (!raw || !Number.isInteger(available) || available < 0) throw new Error("Enter a whole number of units.");
  await request("/demo/inventory", "POST", { incident_id: state.incidentId, available });
  state.selectedPlanId = null;
}, "Stock changed. Earlier plans and approvals no longer apply.").then(checkAlerts).catch(() => {}));
$("link-account").addEventListener("click", () => { linkAccount().catch((error) => message(error.message || String(error))); });
document.addEventListener("click", (event) => {
  if ($("account-menu").open && !$("account-menu").contains(event.target)) $("account-menu").open = false;
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape" || !$("account-menu").open) return;
  $("account-menu").open = false;
  $("account-menu").querySelector("summary").focus();
});
$("sign-out").addEventListener("click", () => {
  signOut();
  message("Signed out. You're a guest: you can read and ask, but not act.", true);
});
$("alerts-bell").addEventListener("click", async () => {
  const alert = alerts.elsewhere();
  if (!alert || state.busy) return;
  await selectIncident(alert.incident_id).catch(() => {});
  if (state.incidentId === alert.incident_id) await alerts.announce(alert);
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

setUpVoice();
renderConversation();
state.token = storedToken();
const resumed = readSession();
if (resumed) {
  state.session = resumed;
  state.token = resumed.access;
}
setInterval(() => { checkAlerts().catch(() => {}); }, 5000);
let authSettled = () => {};
const authReady = new Promise((resolve) => { authSettled = resolve; });
const authStartup = createStartup({
  attempt: async () => {
    try {
      await loadAuth();
    } finally {
      authSettled();
    }
  },
  onFailure: () => {
    $("auth-status").hidden = false;
    $("auth-status").classList.add("visible");
  },
  onSuccess: () => {
    const retryFocused = document.activeElement === $("auth-retry");
    $("auth-status").hidden = true;
    $("auth-status").classList.remove("visible");
    lockApprover(state.session);
    if (retryFocused && state.auth.enabled) $(state.session ? "sign-out" : "link-account").focus();
    if (state.snapshot) recallMemory();
  },
});
$("auth-retry").addEventListener("click", () => authStartup.start());
authStartup.start();

let connectedOnce = false;
function afterConnected() {
  if (connectedOnce) return;
  connectedOnce = true;
  lockApprover(state.session);
  loadVoice();
  recallMemory();
  checkAlerts().catch(() => {});
  const parked = storedPurchase();
  if (parked) {
    say("assistant", parkedPurchaseLine(parked, dollars));
  }
}

let retryHadFocus = false;
const startup = createStartup({
  attempt: async () => {
    await authReady;
    $("connection").textContent = "Connecting";
    $("connection").className = "connection";
    await act(async () => {}, "");
  },
  retryable: (error) => error.status !== 401,
  onFailure: (error, { retryIn }) => {
    $("retry").hidden = false;
    if (error.status === 401) return;
    $("connection").textContent = "Offline";
    $("connection").className = "connection error";
    if (!state.snapshot) $("incident-status").textContent = "Offline";
    const reason = error.status === 0 || error instanceof TypeError ? "I couldn't reach LogiOps."
      : error.status >= 500 ? "LogiOps isn't answering right now." : error.message || String(error);
    message(`${reason} ${retryIn ? "Trying again shortly." : "Press Retry to try again."}`);
  },
  onSuccess: (recovered) => {
    $("retry").hidden = true;
    if (recovered) message("Connected.", true);
    if (retryHadFocus) $("ask-input").focus({ preventScroll: true });
    retryHadFocus = false;
    afterConnected();
  },
});
$("retry").addEventListener("click", () => {
  if (state.busy) return;
  retryHadFocus = document.activeElement === $("retry");
  startup.start();
});
startup.start();
