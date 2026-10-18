"use strict";

import { createApi, createStorage, explainError as explain } from "../app/api.js";
import { createMcpClient } from "../app/mcp.js";
import { createMcpAppHost } from "../app/mcp-host.js";
import { createVoice } from "../app/voice.js";
import { createMemory } from "../app/memory.js";
import { describePreferences, mergedPreferences, preferenceEffect as effectOf } from "../app/preferences.js";
import { createPurchase, dollars } from "../app/purchase.js";
import { createAlerts, bellText } from "../app/alerts.js";
import { createCommands, approvalReadback } from "../app/commands.js";
import { createStore } from "../app/store.js";
import {
  visibleVersion, visibleApproval, visiblePlans, latestAgentEvent, namedPlanKinds,
  recommendedPlan as pickRecommended, planFromUtterance as pickFromUtterance, TIME_ZONE,
} from "../app/selectors.js";
import { welcomeText as greeting } from "../app/greeting.js";
import { checkBadge, checkNote, fallbackNote, traceSummary, executionSummary } from "../app/run-badges.js";
import { renderMarkdown } from "../app/markdown-dom.js";
import { sessionFigures, incidentTimes } from "../app/metrics.js";
import { SURFACES, createSurfaces, shortSpoken, homeCards, displayPlan, chipsFor } from "./surfaces.js";
import { createCarousel } from "./carousel.js";
import {
  el, renderHome, renderIncident, renderPlanList, renderConfirm, renderReceipt, renderAlert, renderResult, renderTrace, renderTranscript,
} from "./render.js";

const $ = (id) => document.getElementById(id);
const DEFAULT_INCIDENT = "SHIP-421";
const route = window.LogiOpsRoute;
const markdown = window.LogiOpsMarkdown;
const intent = window.LogiOpsIntent;
const CLOCK = new Intl.DateTimeFormat("en-US", { timeZone: TIME_ZONE, weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZoneName: "short" });
const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const hashIncident = () => decodeURIComponent(location.hash.slice(1)).trim().toUpperCase() || DEFAULT_INCIDENT;
const MCP_APP = { uriPrefix: "ui://logiops/resolution-options", proxyPath: "/mcp-app/sandbox.html" };
const SANDBOX_ORIGIN = (() => {
  const value = document.querySelector('meta[name="logiops-sandbox-origin"]')?.content || "";
  try {
    const url = new URL(value);
    return /^https?:$/.test(url.protocol) && url.origin !== location.origin ? url.origin : null;
  } catch (_) { return null; }
})();

const store = createStore({
  token: "", snapshot: null, selectedPlanId: null, busy: false, conversation: [], app: null, lastRun: null,
  awaitingExecute: false, pendingApproval: null, incidentId: hashIncident(), inbox: [], conversations: {}, selections: {},
  briefingPick: null, cardTheme: "dark", voice: { engine: "browser", voice: null, fillers: [] }, auth: { enabled: false }, session: null,
  memoryIncident: null, approver: "demo-operator", metrics: null,
});
const state = store.state;
const surfaces = createSurfaces(location.hash ? "incident" : "home");
const sections = Object.fromEntries(SURFACES.map((name) => [name, document.querySelector(`[data-surface="${name}"]`)]));
const incidentPath = (suffix = "") => `/incidents/${encodeURIComponent(state.incidentId)}${suffix}`;
const orb = { state: "ready", started: 0, ticker: 0 };
let traceTimers = [];

function message(text, success = false) {
  const box = $("message");
  box.textContent = text;
  box.className = text ? `message visible${success ? " success" : ""}` : "message";
  box.setAttribute("role", success || !text ? "status" : "alert");
  box.setAttribute("aria-live", success || !text ? "polite" : "assertive");
}

function tick() {
  $("device-clock").textContent = CLOCK.format(new Date());
}

function elapsed() {
  if (orb.started) $("device-elapsed").textContent = `${Math.floor((performance.now() - orb.started) / 1000)} s`;
}

function setVoice(event, speaking = false) {
  const next = route.voiceState(orb.state, event, speaking);
  if (next.state === "thinking" && orb.state !== "thinking") {
    orb.started = performance.now();
    $("device-elapsed").textContent = "0 s";
    clearInterval(orb.ticker);
    orb.ticker = setInterval(elapsed, 250);
  } else if (next.state !== "thinking" && orb.state === "thinking") {
    clearInterval(orb.ticker);
    if (orb.started) $("device-elapsed").textContent = `answered in ${((performance.now() - orb.started) / 1000).toFixed(1)} s`;
    orb.started = 0;
  }
  orb.state = next.state;
  $("device-orb").dataset.state = orb.state;
  if ($("device-state").textContent !== next.label) $("device-state").textContent = next.label;
}

function device(method, ...args) {
  if (method === "voice") setVoice(...args);
  else if (method === "heard") $("device-heard").textContent = args[0];
  else if (method === "reply") {
    const [text, spoken, speaking] = args;
    $("device-spoken").textContent = shortSpoken(text, spoken, markdown.plainText);
    $("more").hidden = false;
    setVoice("reply", speaking);
  }
}

function setBusy(busy) {
  store.set({ busy });
  renderControls();
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
    state.approver = session?.username || "demo-operator";
    renderAccount();
  },
  onAgentCall: (phase) => {
    if (phase === "request") {
      device("voice", "request");
      startFiller();
      return;
    }
    voice.cancelFiller();
    if (phase === "error") device("voice", "error");
  },
});
const { request, storedToken, storeToken, readSession, keepSession, signOut, randomText } = api;

function showSurface(name, payload) {
  paintSurface(surfaces.show(name, payload));
}

const purchase = createPurchase({
  storage: createStorage(), request, crypto: window.crypto,
  api: { token: () => state.token, fetch: (...args) => fetch(...args), explain: explainError },
  selectors: { visiblePlans, visibleApproval, namedPlanKinds, planFromUtterance: (text) => planFromUtterance(text) },
  snapshot: () => state.snapshot, incidentId: () => state.incidentId,
  say: (...args) => say(...args), act: (...args) => act(...args), approvePlan: (plan) => approvePlan(plan),
  onReadback: (pending, plan) => showSurface("confirm", { kind: "purchase", purchase: pending, plan }),
  onBooking: (booking) => showSurface("receipt", { booking }),
});

const alerts = createAlerts({
  request, incidentId: () => state.incidentId, isBusy: () => state.busy, isHidden: () => document.hidden,
  onAlerts: () => renderAlertBell(),
  onAnnounce: async (alert) => {
    state.pendingApproval = null;
    state.awaitingExecute = false;
    if (purchase.pending()?.incidentId === alert.incident_id || purchase.stored()?.incidentId === alert.incident_id) purchase.forget();
    state.selectedPlanId = alert.new_plan?.plan_id || null;
    await refresh().catch(() => {});
    say("assistant", alert.message, "proactive alert · nothing approved", alert.spoken);
    showSurface("alert", { alert });
  },
});
const checkAlerts = () => alerts.check();

function renderAccount() {
  const button = $("account");
  button.hidden = !state.auth.enabled;
  button.classList.toggle("signed-in", Boolean(state.session));
  button.textContent = state.session ? state.session.username : "Guest";
  button.setAttribute("aria-label", state.session ? `Signed in as ${state.session.username}; sign out` : "Guest, read only; link your account");
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
  if (outcome.path.startsWith("/console")) {
    location.replace(outcome.path);
    return new Promise(() => {});
  }
  history.replaceState(null, "", outcome.path);
  state.signInNote = outcome.note;
}

const mcpClient = createMcpClient({ getToken: () => state.token });

function hostContext() {
  const width = Math.round(Math.max(280, ($("surface")?.clientWidth || window.innerWidth) - 36));
  return {
    theme: state.cardTheme, displayMode: "inline", availableDisplayModes: ["inline"],
    containerDimensions: { width, maxHeight: 640 }, locale: navigator.language || "en-US", timeZone: TIME_ZONE,
    platform: "web", deviceClass: width < 480 ? "compact" : "regular",
    deviceCapabilities: { touch: matchMedia("(pointer: coarse)").matches, hover: matchMedia("(hover: hover)").matches },
    safeAreaInsets: { top: 0, right: 0, bottom: 0, left: 0 },
  };
}

const mcpHost = createMcpAppHost({
  sandboxOrigin: SANDBOX_ORIGIN, hostOrigin: location.origin, proxyPath: MCP_APP.proxyPath, slot: $("mcp-app-slot"),
  mcp: mcpClient, uriPrefix: MCP_APP.uriPrefix, hostInfo: { name: "LogiOps Alexa+ device (simulated)", version: "2.0.0" },
  hostContext, frameTitle: "Resolution options (MCP App)", rejectMessage: "Unknown or unavailable plan, or the device is busy",
  onMessage: (params) => selectFromApp(params),
  onHide: () => { $("mcp-app").hidden = true; $("plans").hidden = false; },
});

async function showMcpApp(run) {
  const step = run.tool_trace?.find((item) => item.tool === "investigate_incident" && !item.is_error);
  if (!step) return;
  if (!SANDBOX_ORIGIN) {
    showMcpAppNote("The interactive card needs a second origin for its sandbox, and none is available on this address. "
      + "Open the demo on 127.0.0.1 or localhost, or on the deployed hostname. The plans are listed below.");
    return;
  }
  const wanted = { incidentId: state.incidentId, version: step.output.source_version };
  const resource = await mcpHost.show({
    toolName: "investigate_incident", input: step.input,
    result: {
      content: [{ type: "text", text: JSON.stringify(step.output) }], structuredContent: step.output,
      _meta: { "logiops/recommended_plan_id": recommendedPlan(state.snapshot)?.id || null },
    },
    stillWanted: () => Boolean(state.snapshot) && String(step.input?.shipment_id || "").trim().toUpperCase() === state.incidentId
      && wanted.version === visibleVersion(state.snapshot),
  });
  if (!resource) return;
  state.app = wanted;
  $("mcp-app").classList.toggle("borderless", !resource.prefersBorder);
  $("mcp-app").hidden = false;
  $("plans").hidden = true;
}

function hideMcpApp(reason = "hidden") {
  state.app = null;
  mcpHost.hide(reason);
}

function showMcpAppNote(text) {
  state.app = null;
  mcpHost.hide("note");
  const note = el("p", "mcp-app-note", text);
  $("mcp-app-slot").replaceChildren(note);
  $("mcp-app").hidden = false;
  $("plans").hidden = false;
}

$("mcp-app-theme").addEventListener("click", () => {
  state.cardTheme = state.cardTheme === "dark" ? "light" : "dark";
  $("mcp-app-theme").setAttribute("aria-pressed", String(state.cardTheme === "light"));
  mcpHost.notifyContext();
});
let contextTimer = 0;
window.addEventListener("resize", () => {
  clearTimeout(contextTimer);
  contextTimer = setTimeout(() => mcpHost.notifyContext(), 200);
});

function selectPlan(plan) {
  if (!plan || !state.snapshot || state.busy) return false;
  if (visibleApproval(state.snapshot) || state.snapshot.executions.length) return false;
  state.selectedPlanId = plan.id;
  state.pendingApproval = { planId: plan.id, sourceVersion: plan.source_version };
  say("assistant", `${approvalReadback(plan)} Say “yes” to approve it, or ask me anything else.`);
  showSurface("confirm", { kind: "approval", plan });
  return true;
}

function selectFromApp(params) {
  const text = params?.content?.type === "text" ? String(params.content.text) : "";
  const match = text.match(/^Select plan (\S+)$/);
  if (!match || !state.snapshot) return false;
  return selectPlan(visiblePlans(state.snapshot).find((item) => item.id === match[1]));
}

function recommendedPlan(snapshot) {
  return pickRecommended(snapshot, intent);
}

function currentPlan() {
  return state.snapshot ? displayPlan(state.snapshot, state.selectedPlanId, recommendedPlan(state.snapshot)) : null;
}

function summaryOf() {
  return state.inbox.find((item) => item.incident_id === state.incidentId) || null;
}

function welcomeText() {
  return greeting({ inbox: state.inbox, incidentId: state.incidentId });
}

const carousel = createCarousel({ root: $("inbox"), onOpen: (id) => selectIncident(id).catch(() => {}), reducedMotion });
let carouselKey = "";

function updateCarousel(cards) {
  const key = JSON.stringify([cards.map((card) => [card.incident_id, card.status, card.critical_units_at_risk, card.startHere]), state.incidentId]);
  if (key === carouselKey) return;
  carouselKey = key;
  carousel.update(cards, state.incidentId);
}

function renderPlansSurface() {
  const snapshot = state.snapshot;
  if (!snapshot) return;
  const plans = visiblePlans(snapshot);
  const approval = visibleApproval(snapshot);
  const executed = snapshot.executions.length > 0;
  const recommended = recommendedPlan(snapshot);
  if (approval) state.selectedPlanId = approval.plan_id;
  else if (!plans.some((plan) => plan.id === state.selectedPlanId)) state.selectedPlanId = recommended?.id || plans[0]?.id || null;
  $("plans-title").textContent = plans.length ? `${plans.length} plans for ${snapshot.state.incident_id}` : `No plans yet for ${snapshot.state.incident_id}`;
  $("plans-state").textContent = executed ? "Executed and verified" : approval ? `Approved by ${approval.approved_by} · say “execute it”`
    : plans.length ? "Only you approve. Selecting a plan does not approve it." : "Ask what's happening to calculate them";
  renderPlanList($("plans"), {
    plans: recommended ? [recommended, ...plans.filter((plan) => plan.id !== recommended.id)] : plans, selectedId: state.selectedPlanId, recommendedId: recommended?.id, preferredId: snapshot.preference?.preferred_plan_id,
    locked: Boolean(approval || executed), onSelect: (plan) => selectPlan(plan),
  });
}

function paintSurface(shown = surfaces.current()) {
  for (const [name, section] of Object.entries(sections)) section.hidden = name !== shown.name;
  const section = sections[shown.name];
  const snapshot = state.snapshot;
  if (shown.name === "home") {
    renderHome(section, { greeting: welcomeText(), lead: shown.payload.lead, session: state.metrics ? sessionFigures(state.metrics.session) : null });
    updateCarousel(homeCards(state.inbox, shown.payload.pick ?? state.briefingPick));
  } else if (shown.name === "incident" && snapshot) {
    renderIncident(section, { snapshot, plan: currentPlan(), summary: summaryOf(), route });
  } else if (shown.name === "plans") {
    renderPlansSurface();
  } else if (shown.name === "confirm") {
    renderConfirm(section, shown.payload, { onYes: () => handleUtterance("yes"), onNo: () => handleUtterance("no") });
  } else if (shown.name === "receipt") {
    const booking = shown.payload.booking;
    renderReceipt(section, { booking, onOpen: () => openReceipt(booking.number).catch((error) => message(error.message || String(error))) });
  } else if (shown.name === "alert") {
    renderAlert(section, shown.payload.alert);
  } else if (shown.name === "result" && snapshot?.executions[0]) {
    const execution = snapshot.executions[0];
    renderResult(section, {
      snapshot, execution, plan: snapshot.plans.find((plan) => plan.id === execution.plan_id), booking: (snapshot.bookings || []).at(-1) || null,
      times: incidentTimes(state.metrics?.incidents.find((item) => item.incident_id === state.incidentId)),
    });
  }
  renderChips(shown.name);
  $("surface").scrollTop = 0;
}

function renderChips(surface) {
  const box = $("chips");
  box.replaceChildren();
  for (const [text, utterance] of chipsFor(surface, { snapshot: state.snapshot, incidentId: state.incidentId, inbox: state.inbox, plan: currentPlan() })) {
    const chip = el("button", "chip", text);
    chip.type = "button";
    chip.dataset.say = utterance;
    chip.disabled = state.busy || !state.snapshot;
    chip.addEventListener("click", () => handleUtterance(utterance));
    box.append(chip);
  }
}

function paintTalk() {
  const heard = [...state.conversation].reverse().find((turn) => turn.role === "user");
  const reply = [...state.conversation].reverse().find((turn) => turn.role === "assistant");
  $("device-heard").textContent = heard ? heard.text : "Try “any delays today?”";
  $("device-spoken").textContent = reply ? shortSpoken(reply.text, null, markdown.plainText) : "Ask about the queue, an incident, or a plan.";
  $("more").hidden = !state.conversation.length;
}

function renderControls() {
  const ready = Boolean(state.snapshot) && !state.busy;
  $("ask").disabled = !ready;
  $("ask-input").disabled = !ready;
  $("mic").disabled = !ready;
  for (const chip of document.querySelectorAll(".chip")) chip.disabled = !ready;
  for (const id of ["confirm-yes", "confirm-no"]) if ($(id)) $(id).disabled = state.busy;
  $("account").disabled = state.busy;
}

function render(snapshot) {
  state.snapshot = snapshot;
  if (state.app && (state.app.incidentId !== snapshot.state.incident_id || state.app.version !== visibleVersion(snapshot))) hideMcpApp();
  $("connection").textContent = "Connected";
  $("connection").className = "connection ready";
  document.title = `LogiOps AI · ${snapshot.state.incident_id}`;
  $("console-link").href = `/console#${encodeURIComponent(state.incidentId)}`;
  const agentEvent = latestAgentEvent(snapshot);
  if (!state.conversation.length && agentEvent) {
    state.conversation.push({ role: "assistant", text: agentEvent.data.display_answer || agentEvent.data.answer, meta: traceSummary(agentEvent.data), check: checkBadge(agentEvent.data) });
  }
  paintTalk();
  paintSurface();
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
  state.metrics = await request("/metrics");
  const shown = surfaces.current();
  if (shown.name === "home") renderHome(sections.home, { greeting: welcomeText(), lead: shown.payload.lead, session: sessionFigures(state.metrics.session) });
  else if (shown.name === "result") paintSurface();
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
  hideMcpApp("incident changed");
  surfaces.show("incident");
  await act(async () => {}, "");
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
      $("account").focus();
    } else if (error.status === 401) {
      storeToken("");
      $("connection").textContent = "Token required";
      $("connection").className = "connection error";
      message("This server needs the operator token. Open the operator console, paste it under Developer, and come back.");
    }
    throw error;
  } finally { setBusy(false); }
}

async function approvePlan(plan) {
  if (!plan) throw new Error("Select a plan first.");
  await request(incidentPath("/approvals"), "POST", { plan_id: plan.id, source_version: plan.source_version, approved_by: state.approver });
}

async function executeApproved() {
  const approval = visibleApproval(state.snapshot);
  if (!approval) throw new Error("No plan is approved for the current incident version.");
  await request(incidentPath("/execute"), "POST", { plan_id: approval.plan_id, source_version: approval.source_version });
}

function planFromUtterance(text) {
  return pickFromUtterance(text, state.snapshot, intent);
}

async function openReceipt(number) {
  const html = await purchase.openReceipt(number);
  const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
  window.open(url, "_blank");
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

function renderAlertBell() {
  const bell = $("alerts-bell");
  const shown = bellText(alerts.current(), state.incidentId);
  bell.hidden = !shown;
  bell.textContent = shown ? shown.text : "";
  bell.setAttribute("aria-label", shown ? shown.label : "No proactive alerts");
}

const memory = createMemory({
  storage: createStorage(), request, randomText,
  credentials: () => ({ token: state.token, session: state.session, auth: state.auth }),
  incident: () => state.incidentId,
});
const remember = (role, text) => memory.remember(role, text);

async function recallMemory() {
  const recalled = await memory.recall();
  if (!recalled) return;
  state.memoryIncident = recalled.last_incident || null;
  if (recalled.welcome && !state.conversation.some((turn) => turn.role === "user")) {
    say("assistant", recalled.welcome, "welcome back · from memory", recalled.welcome);
    if (surfaces.current().name === "home") showSurface("home", { lead: recalled.welcome });
  }
}

function say(role, text, meta, spoken, check) {
  state.conversation.push({ role, text, meta, check });
  if (!state.forgetting && !String(meta || "").startsWith("welcome back")) remember(role, role === "assistant" ? (spoken || markdown.plainText(text)) : text);
  if (!$("sheet").hidden) renderTranscript($("conversation"), state.conversation, (source) => renderMarkdown(source, { markdown }));
  if (role !== "assistant") {
    device("heard", text);
    return;
  }
  const speaking = speechOn();
  device("reply", text, spoken, speaking);
  if (speaking) speak(spoken || markdown.plainText(text));
}

function speechOn() {
  return $("speak-replies").checked && (state.voice.engine === "polly" || "speechSynthesis" in window);
}

const voice = createVoice({ getToken: () => state.token, getConfig: () => state.voice, isEnabled: speechOn, device });
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

function paintTrace() {
  for (const timer of traceTimers) clearTimeout(timer);
  traceTimers = renderTrace($("device-trace"), state.lastRun, { check: state.lastRun ? checkBadge(state.lastRun) : null, reducedMotion: reducedMotion() });
}

const commands = createCommands({
  store, intent, request, purchase,
  selectors: { visiblePlans, visibleApproval, namedPlanKinds, latestAgentEvent, visibleVersion, planFromUtterance: (text) => planFromUtterance(text) },
  badges: { checkBadge, traceSummary, executionSummary, noteCheck, noteFallback },
  preferences: { describe: describePreferences, effect: effectOf },
  say, act, device, stopSpeaking, selectIncident, hideMcpApp, showMcpApp, showMcpAppNote,
  onInbox: () => paintSurface(), onRun: (run) => { state.lastRun = run; if (!$("sheet").hidden) paintTrace(); },
  onSurface: (name, payload) => showSurface(name, payload),
  approvePlan, executeApproved, savePreferences: (update) => request("/operator/preferences", "PUT", mergedPreferences(state.snapshot?.operator_preferences, update)),
  linkAccount, signOut,
});

function handleUtterance(raw) {
  return commands.handle(raw);
}

function openSheet() {
  renderTranscript($("conversation"), state.conversation, (source) => renderMarkdown(source, { markdown }));
  paintTrace();
  $("sheet").hidden = false;
  $("sheet-close").focus();
}

function closeSheet() {
  $("sheet").hidden = true;
  $("more").focus();
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
    mic.setAttribute("aria-pressed", "false");
    mic.setAttribute("aria-label", "Speak");
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
    mic.setAttribute("aria-pressed", "true");
    mic.setAttribute("aria-label", "Listening…");
    device("voice", "listen-start");
    recognition.start();
  });
}

window.addEventListener("hashchange", () => {
  const id = hashIncident();
  if (id !== state.incidentId) selectIncident(id).catch(() => {});
});
$("account").addEventListener("click", () => handleUtterance(state.session ? "sign out" : "link my account"));
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
$("more").addEventListener("click", openSheet);
$("sheet-close").addEventListener("click", closeSheet);
$("sheet").addEventListener("click", (event) => { if (event.target === $("sheet")) closeSheet(); });
window.addEventListener("keydown", (event) => { if (event.key === "Escape" && !$("sheet").hidden) closeSheet(); });

tick();
setInterval(tick, 30000);
setVoice("error");
setUpVoice();
paintTalk();
paintSurface();
state.token = storedToken();
const resumed = readSession();
if (resumed) {
  state.session = resumed;
  state.token = resumed.access;
  state.approver = resumed.username || "demo-operator";
}
setInterval(() => { checkAlerts().catch(() => {}); }, 5000);
loadAuth().then(finishSignIn).catch(() => {}).then(() => act(async () => {}, "").catch(() => {})).then(() => {
  if (state.signInNote) say("assistant", state.signInNote);
  loadVoice();
  recallMemory();
  checkAlerts().catch(() => {});
  const parked = purchase.stored();
  if (parked) {
    say("assistant", `A booking is waiting for “${parked.quote.plan_label}” on ${parked.incidentId} (${dollars(parked.quote.total_usd)}). `
      + "Say “resume” to hear the price again, or “no” to drop it. Nothing was charged.");
  }
}).catch(() => {});
