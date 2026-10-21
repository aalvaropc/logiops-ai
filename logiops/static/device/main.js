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
  visibleVersion, visibleApproval, visiblePlans, latestAgentEvent, namedPlanKinds, plural,
  recommendedPlan as pickRecommended, planFromUtterance as pickFromUtterance, TIME_ZONE,
} from "../app/selectors.js";
import { homeHeading } from "../app/greeting.js";
import { checkBadge, checkNote, fallbackNote, traceSummary, executionSummary } from "../app/run-badges.js";
import { renderMarkdown } from "../app/markdown-dom.js";
import { sessionFigures, incidentTimes } from "../app/metrics.js";
import { SURFACES, createSurfaces, shortSpoken, homeCards, livePick, displayPlan, chipsFor, lifecycleStep, stageLine, stageCaption, agentLine } from "./surfaces.js";
import { createQueue } from "./queue.js";
import { createStage } from "./stage.js";
import {
  el, renderHome, renderSession, renderIncident, renderPlanList, renderConfirm, renderReceipt, renderAlert, renderResult, renderTranscript, renderAgentLine,
} from "./render.js";

const $ = (id) => document.getElementById(id);
const route = window.LogiOpsRoute;
const journey = window.LogiOpsJourney;
const markdown = window.LogiOpsMarkdown;
const intent = window.LogiOpsIntent;
const CLOCK = new Intl.DateTimeFormat("en-US", { timeZone: TIME_ZONE, weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZoneName: "short" });
const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const hashIncident = () => decodeURIComponent(location.hash.slice(1)).trim().toUpperCase() || null;
const MCP_APP = { uriPrefix: "ui://logiops/resolution-options", proxyPath: "/mcp-app/sandbox.html" };
const SANDBOX_ORIGIN = (() => {
  const value = document.querySelector('meta[name="logiops-sandbox-origin"]')?.content || "";
  try {
    const url = new URL(value);
    return /^https?:$/.test(url.protocol) && url.origin !== location.origin ? url.origin : null;
  } catch (_) { return null; }
})();

const store = createStore({
  token: "", snapshot: null, selectedPlanId: null, busy: false, conversation: [], app: null,
  awaitingExecute: false, pendingApproval: null, incidentId: hashIncident(), inbox: [], conversations: {}, selections: {},
  briefingPick: null, cardTheme: "dark", voice: { engine: "browser", voice: null, fillers: [] }, auth: { enabled: false }, session: null,
  memoryIncident: null, approver: "demo-operator", metrics: null,
});
const state = store.state;
const surfaces = createSurfaces(location.hash ? "incident" : "home");
const sections = Object.fromEntries(SURFACES.map((name) => [name, document.querySelector(`[data-surface="${name}"]`)]));
const incidentPath = (suffix = "") => `/incidents/${encodeURIComponent(state.incidentId)}${suffix}`;
const orb = { state: "ready", started: 0, ticker: 0, answered: null };
const stage = createStage({ root: $("agent-stage"), surface: $("surface"), quiet: [$("chips"), $("more")], reducedMotion });
let shownTrace = null;
let inFlight = false;
let hushes = 0;

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
  if (!orb.started) return;
  const seconds = Math.floor((performance.now() - orb.started) / 1000);
  $("device-elapsed").textContent = `${seconds} s`;
  stage.tick(seconds);
}

function setVoice(event, speaking = false, at = performance.now()) {
  const next = route.voiceState(orb.state, event, speaking);
  if (next.state === "thinking" && orb.state !== "thinking") {
    orb.started = performance.now();
    $("device-elapsed").textContent = "0 s";
    clearInterval(orb.ticker);
    orb.ticker = setInterval(elapsed, 250);
  } else if (next.state !== "thinking" && orb.state === "thinking") {
    clearInterval(orb.ticker);
    orb.answered = orb.started ? (at - orb.started) / 1000 : null;
    if (orb.answered !== null) $("device-elapsed").textContent = `answered in ${orb.answered.toFixed(1)} s`;
    orb.started = 0;
  }
  orb.state = next.state;
  $("device-orb").dataset.state = orb.state;
  document.querySelector(".talk").dataset.voice = orb.state;
  if ($("device-state").textContent !== next.label) $("device-state").textContent = next.label;
  $("ask-input").placeholder = orb.state === "ready" ? "Ask LogiOps" : next.label;
}

function device(method, ...args) {
  if (method === "voice") setVoice(...args);
  else if (method === "heard") {
    $("heard-label").hidden = false;
    $("device-heard").textContent = args[0];
  }
  else if (method === "reply") {
    const [text, spoken, speaking] = args;
    const at = performance.now();
    const stray = inFlight;
    const hush = hushes;
    stage.whenGone(() => {
      const voiced = !stray && speaking && hush === hushes && speechOn();
      $("device-spoken").textContent = shortSpoken(text, spoken, markdown.plainText);
      document.querySelector(".talk").classList.remove("expanded");
      document.querySelector(".talk").classList.add("replied");
      $("more").hidden = false;
      if (!stray && orb.state !== "listening") setVoice("reply", voiced, at);
      if (voiced) speak(spoken || markdown.plainText(text));
    });
    if (!stray) stage.settle();
  }
  else if (method === "trace") {
    clearInterval(orb.ticker);
    const seconds = orb.started ? (performance.now() - orb.started) / 1000 : orb.answered;
    stage.replay(args[0], checkBadge(args[0]), (live) => stageCaption(args[0], seconds, live));
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
  onAgentCall: (phase, path) => {
    if (phase === "request") {
      const asking = stageLine(path);
      stage.ask(asking);
      inFlight = true;
      device("voice", "request");
      $("device-spoken").textContent = `${asking.filter(Boolean).join(" ")}…`;
      startFiller();
      return;
    }
    inFlight = false;
    voice.cancelFiller();
    if (phase === "error") {
      device("voice", "error");
      stage.clear();
    }
  },
});
const { request, streamed, storedToken, storeToken, readSession, keepSession, signOut, randomText } = api;

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

const mcpClient = createMcpClient({ getToken: () => state.token });

const alerts = createAlerts({
  request, list: () => mcpClient.callTool("list_alerts"), incidentId: () => state.incidentId, isBusy: () => state.busy, isHidden: () => document.hidden,
  onAlerts: () => renderAlertBell(),
  onAnnounce: async (alert) => {
    state.pendingApproval = null;
    state.awaitingExecute = false;
    if (purchase.pending()?.incidentId === alert.incident_id || purchase.stored()?.incidentId === alert.incident_id) purchase.forget();
    state.selectedPlanId = alert.new_plan?.plan_id || null;
    await refresh().catch(() => {});
    say("assistant", alert.message, alert.approval_invalidated ? "proactive alert · approval invalidated" : "proactive alert · nothing approved", alert.spoken);
    showSurface("alert", { alert });
  },
});
const checkAlerts = () => alerts.check();

function renderAccount() {
  const button = $("account");
  button.hidden = !state.auth.enabled;
  button.classList.toggle("signed-in", Boolean(state.session));
  button.textContent = state.session ? state.session.username : "Link account";
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

function cardWidth() {
  const surface = $("surface");
  const style = getComputedStyle(surface);
  const inner = surface.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
  return Math.round(Math.max(280, $("mcp-app-slot").clientWidth || inner - 4));
}

function hostContext() {
  const width = cardWidth();
  return {
    theme: state.cardTheme, displayMode: "inline", availableDisplayModes: ["inline"],
    containerDimensions: { width }, locale: navigator.language || "en-US", timeZone: TIME_ZONE,
    platform: "web", deviceClass: width < 480 ? "compact" : "regular",
    deviceCapabilities: { touch: matchMedia("(pointer: coarse)").matches, hover: matchMedia("(hover: hover)").matches },
    safeAreaInsets: { top: 0, right: 0, bottom: 0, left: 0 },
  };
}

const mcpHost = createMcpAppHost({
  sandboxOrigin: SANDBOX_ORIGIN, hostOrigin: location.origin, proxyPath: MCP_APP.proxyPath, slot: $("mcp-app-slot"),
  mcp: mcpClient, uriPrefix: MCP_APP.uriPrefix, hostInfo: { name: "LogiOps Alexa+ device (simulated)", version: "2.0.0" },
  hostContext, maxHeight: 2400, frameTitle: "Resolution options (MCP App)", rejectMessage: "Unknown or unavailable plan, or the device is busy",
  onMessage: (params) => selectFromApp(params),
  onHide: () => { $("mcp-app").hidden = true; $("plans").hidden = false; },
  onReady: () => { $("plans").hidden = Boolean(state.app); },
  onError: () => showMcpAppNote("The interactive card is unavailable. The plans are listed below."),
});

function decisionOf(snapshot) {
  return { approved: visibleApproval(snapshot)?.plan_id || null, executed: Boolean(snapshot?.executions.length) };
}

async function showMcpApp(run) {
  const step = run.tool_trace?.find((item) => item.tool === "investigate_incident" && !item.is_error);
  if (!step) return;
  if (!SANDBOX_ORIGIN) {
    showMcpAppNote("The interactive card needs a second origin for its sandbox, and none is available on this address. "
      + "Open the demo on 127.0.0.1 or localhost, or on the deployed hostname. The plans are listed below.");
    return;
  }
  const decision = decisionOf(state.snapshot);
  const wanted = { incidentId: state.incidentId, version: step.output.source_version, run, ...decision };
  const resource = await mcpHost.show({
    toolName: "investigate_incident", input: step.input,
    result: {
      content: [{ type: "text", text: JSON.stringify(step.output) }], structuredContent: step.output,
      _meta: {
        "logiops/recommended_plan_id": recommendedPlan(state.snapshot)?.id || null,
        "logiops/approved_plan_id": decision.approved, "logiops/executed": decision.executed,
      },
    },
    stillWanted: () => Boolean(state.snapshot) && String(step.input?.shipment_id || "").trim().toUpperCase() === state.incidentId
      && wanted.version === visibleVersion(state.snapshot),
  });
  if (!resource) return;
  state.app = wanted;
  $("mcp-app").classList.toggle("borderless", !resource.prefersBorder);
  $("mcp-app").hidden = false;
  $("plans").hidden = mcpHost.ready();
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

function openIncident(id) {
  if (id === state.incidentId && state.snapshot) showSurface("incident");
  else selectIncident(id).catch(() => {});
}

const queue = createQueue({ root: $("inbox"), onOpen: openIncident, labelledBy: "home-title" });
let queueKey = "";

function updateQueue(cards) {
  const key = JSON.stringify([cards.map((card) => [card.incident_id, card.status, card.critical_units_at_risk, card.startHere]), state.incidentId]);
  if (key === queueKey) return;
  queueKey = key;
  queue.update(cards);
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
  $("plans-title").textContent = plans.length ? `${plans.length} ${plural(plans.length, "plan")} for ${snapshot.state.incident_id}` : `No plans yet for ${snapshot.state.incident_id}`;
  const approver = approval?.approved_by === state.approver ? "you" : approval?.approved_by;
  const approvedPlan = approval && plans.find((plan) => plan.id === approval.plan_id);
  $("plans-state").textContent = executed ? "Executed and verified"
    : approval ? `Approved by ${approver}: “${approvedPlan?.label || approval.plan_id}”. Nothing has run yet.`
    : plans.length ? "Only you approve. Selecting a plan does not approve it." : "Ask what's happening to calculate them";
  const investigation = latestAgentEvent(snapshot)?.data;
  renderAgentLine($("plans-agent"), agentLine(investigation, investigation && checkBadge(investigation)), investigation);
  renderPlanList($("plans"), {
    plans: recommended ? [recommended, ...plans.filter((plan) => plan.id !== recommended.id)] : plans, selectedId: state.selectedPlanId, recommendedId: recommended?.id, preferredId: snapshot.preference?.preferred_plan_id,
    locked: Boolean(approval || executed), onSelect: (plan) => selectPlan(plan),
  });
}

let paintedSurface = null;

function paintSurface(shown = surfaces.current()) {
  const lostFocus = !document.activeElement || document.activeElement === document.body || !document.activeElement.isConnected
    || Boolean(document.activeElement.closest?.("[data-surface], #chips"));
  for (const [name, section] of Object.entries(sections)) section.hidden = name !== shown.name;
  const section = sections[shown.name];
  const snapshot = state.snapshot;
  if (shown.name === "home") {
    renderHome(section, {
      heading: homeHeading(state.inbox), inbox: state.inbox, journey, session: state.metrics ? sessionFigures(state.metrics.session) : null,
    });
    updateQueue(homeCards(state.inbox, livePick(state.inbox, shown.payload.pick ?? state.briefingPick)));
  } else if (shown.name === "incident" && snapshot) {
    renderIncident(section, { snapshot, plan: currentPlan(), summary: summaryOf(), route, journey });
  } else if (shown.name === "plans") {
    renderPlansSurface();
  } else if (shown.name === "confirm") {
    renderConfirm(section, shown.payload, {
      onYes: () => handleUtterance("yes"), onNo: () => handleUtterance("no"), labels: snapshot ? visiblePlans(snapshot).map((plan) => plan.label) : [],
      shipment: snapshot?.state.shipment || null, route, journey,
    });
  } else if (shown.name === "receipt") {
    const booking = shown.payload.booking;
    const pending = Boolean(snapshot && visibleApproval(snapshot) && !snapshot.executions.length);
    renderReceipt(section, {
      booking, onOpen: () => openReceipt(booking.number).catch((error) => message(error.message || String(error))),
      onExecute: pending ? () => handleUtterance("Execute the approved plan") : null,
    });
  } else if (shown.name === "alert") {
    renderAlert(section, shown.payload.alert);
  } else if (shown.name === "result" && snapshot?.executions[0]) {
    const execution = snapshot.executions[0];
    renderResult(section, {
      snapshot, execution, plan: snapshot.plans.find((plan) => plan.id === execution.plan_id), booking: (snapshot.bookings || []).at(-1) || null,
      times: incidentTimes(state.metrics?.incidents.find((item) => item.incident_id === state.incidentId)), route, journey,
    });
  }
  renderChips(shown.name);
  paintLifecycle(shown.name);
  $("surface").scrollTop = 0;
  const heading = section.querySelector("h2");
  if (shown.name !== paintedSurface && lostFocus && heading && $("sheet").hidden) {
    heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
  }
  paintedSurface = shown.name;
}

function paintLifecycle(surface) {
  const strip = $("lifecycle");
  const step = surface === "home" ? -1 : lifecycleStep(state.snapshot);
  strip.hidden = step < 0;
  if (step < 0) return;
  strip.setAttribute("aria-label", `${state.snapshot.state.incident_id} progress`);
  [...strip.querySelector("ol").children].forEach((item, index) => {
    item.className = index < step ? "done" : index === step ? "now" : "";
    if (index === step) item.setAttribute("aria-current", "step");
    else item.removeAttribute("aria-current");
  });
}

function renderChips(surface) {
  const box = $("chips");
  box.replaceChildren();
  const pick = surfaces.current().payload.pick ?? state.briefingPick;
  for (const [text, utterance, kind] of chipsFor(surface, { snapshot: state.snapshot, incidentId: state.incidentId, inbox: state.inbox, plan: currentPlan(), pick })) {
    const chip = el("button", kind === "act" ? "chip act" : "chip", text);
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
  $("heard-label").hidden = !heard;
  $("device-heard").textContent = heard ? heard.text : "Try “any delays today?”";
  if (!$("agent-stage").hidden) return;
  $("device-spoken").textContent = reply ? shortSpoken(reply.text, reply.spoken, markdown.plainText) : "Ask about the queue, an incident, or a plan.";
  document.querySelector(".talk").classList.remove("expanded");
  $("more").hidden = !state.conversation.length;
}

function renderControls() {
  const ready = Boolean(state.snapshot) && !state.busy;
  $("ask").disabled = !ready;
  $("ask-input").readOnly = !ready;
  $("mic").disabled = !ready;
  for (const chip of document.querySelectorAll(".chip")) chip.disabled = !ready;
  for (const id of ["confirm-yes", "confirm-no", "receipt-execute"]) if ($(id)) $(id).disabled = state.busy;
  $("account").disabled = state.busy;
}

function render(snapshot) {
  state.snapshot = snapshot;
  if (state.app && (state.app.incidentId !== snapshot.state.incident_id || state.app.version !== visibleVersion(snapshot))) hideMcpApp();
  $("connection").textContent = "Connected";
  $("connection").className = "connection ready";
  document.title = `LogiOps AI · ${snapshot.state.incident_id}`;
  $("console-link").href = `/console#${encodeURIComponent(state.incidentId)}`;
  const decision = decisionOf(snapshot);
  if (state.app && (state.app.approved !== decision.approved || state.app.executed !== decision.executed)) {
    showMcpApp(state.app.run).catch(() => {});
  }
  const agentEvent = latestAgentEvent(snapshot);
  if (!state.conversation.length && agentEvent) {
    state.conversation.push({
      role: "assistant", text: agentEvent.data.display_answer || agentEvent.data.answer, meta: traceSummary(agentEvent.data), check: checkBadge(agentEvent.data),
      spoken: agentEvent.data.spoken, trace: agentEvent.data,
    });
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
  state.inbox = (await mcpClient.callTool("list_incidents").catch(() => request("/incidents"))).incidents;
  if (!state.inbox.some((item) => item.incident_id === state.incidentId)) {
    const unknown = Boolean(state.incidentId);
    state.incidentId = state.inbox[0]?.incident_id || null;
    if (unknown && state.incidentId) history.replaceState(null, "", `#${encodeURIComponent(state.incidentId)}`);
  }
  if (!state.incidentId) throw new Error("The inbox is empty. Import a scenario pack from the operator console.");
  render(await request(incidentPath()));
  loadMetrics().catch(() => {});
}

async function loadMetrics() {
  state.metrics = await request("/metrics");
  const shown = surfaces.current();
  if (shown.name === "home") renderSession(sections.home, sessionFigures(state.metrics.session));
  else if (shown.name === "result") {
    const focused = sections.result.contains(document.activeElement);
    paintSurface();
    const heading = sections.result.querySelector("h2");
    if (focused && heading) {
      heading.tabIndex = -1;
      heading.focus({ preventScroll: true });
    }
  }
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
  if (!approval) throw new Error("No plan is approved for this incident's current data.");
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
  bell.replaceChildren();
  if (shown) bell.append(`${shown.count} alert${shown.count === 1 ? "" : "s"}`, el("span", "bell-where", ` · ${shown.incidentId}`));
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
  }
}

function say(role, text, meta, spoken, check) {
  state.conversation.push({ role, text, meta, check, spoken });
  if (!state.forgetting && !String(meta || "").startsWith("welcome back")) remember(role, role === "assistant" ? (spoken || markdown.plainText(text)) : text);
  if (!$("sheet").hidden) paintSheet();
  if (role !== "assistant") {
    device("heard", text);
    return;
  }
  const speaking = speechOn();
  device("reply", text, spoken, speaking);
}

function paintVoiceToggle() {
  const toggle = $("device-orb");
  toggle.disabled = $("speak-toggle").hidden;
  toggle.setAttribute("aria-pressed", String(!toggle.disabled && $("speak-replies").checked));
}

function setSpeech(on) {
  $("speak-replies").checked = on;
  if (!on) stopSpeaking();
  paintVoiceToggle();
}

function speechOn() {
  return $("speak-replies").checked && (state.voice.engine === "polly" || "speechSynthesis" in window);
}

const voice = createVoice({ getToken: () => state.token, getConfig: () => state.voice, isEnabled: speechOn, device });
const stopSpeaking = (options) => {
  hushes += 1;
  voice.stop(options);
};
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
  paintVoiceToggle();
}

function paintSheet() {
  const latest = state.conversation.findLast((turn) => turn.trace?.tool_trace?.length)?.trace || null;
  renderTranscript($("conversation"), state.conversation, (source) => renderMarkdown(source, { markdown }), { fresh: latest === shownTrace || reducedMotion() ? null : latest });
  shownTrace = latest;
}

function setBackgroundInert(inert) {
  for (const node of [...$("device").children, document.querySelector(".stage-note")]) if (node && node.id !== "sheet") node.inert = inert;
}

const commands = createCommands({
  store, intent, request, purchase,
  selectors: { visiblePlans, visibleApproval, namedPlanKinds, latestAgentEvent, visibleVersion, planFromUtterance: (text) => planFromUtterance(text) },
  badges: { checkBadge, traceSummary, executionSummary, noteCheck, noteFallback },
  preferences: { describe: describePreferences, effect: effectOf },
  say, act, device, stopSpeaking, selectIncident, hideMcpApp, showMcpApp, showMcpAppNote,
  onInbox: () => paintSurface(),
  onRun: (run) => {
    const turn = state.conversation.at(-1);
    if (turn?.role === "assistant") turn.trace = run;
    if (!$("sheet").hidden) paintSheet();
  },
  onSurface: (name, payload) => showSurface(name, payload),
  approvePlan, executeApproved, savePreferences: (update) => request("/operator/preferences", "PUT", mergedPreferences(state.snapshot?.operator_preferences, update)),
  investigate: (path, body) => streamed(`${path}/stream`, body, (step, kind) => (kind === "restart" ? stage.restart() : stage.step(step))),
  linkAccount, signOut,
});

function handleUtterance(raw) {
  if (!state.busy) message("");
  return commands.handle(raw);
}

function openSheet() {
  $("sheet").hidden = false;
  setBackgroundInert(true);
  paintSheet();
  $("sheet-close").focus();
}

function closeSheet() {
  $("sheet").hidden = true;
  setBackgroundInert(false);
  $("more").focus();
}

function setUpVoice() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if ("speechSynthesis" in window) $("speak-toggle").hidden = false;
  paintVoiceToggle();
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
  if (id && id !== state.incidentId) selectIncident(id).catch(() => {});
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
  if (document.activeElement === $("ask")) input.focus({ preventScroll: true });
  handleUtterance(text);
});
$("more").addEventListener("click", openSheet);
$("device-orb").addEventListener("click", () => setSpeech(!$("speak-replies").checked));
$("speak-replies").addEventListener("change", () => setSpeech($("speak-replies").checked));
$("device-spoken").addEventListener("click", () => {
  const line = $("device-spoken");
  const talk = document.querySelector(".talk");
  if (talk.classList.contains("expanded") || line.scrollHeight > line.clientHeight + 1) talk.classList.toggle("expanded");
});
$("sheet-close").addEventListener("click", closeSheet);
$("sheet").addEventListener("click", (event) => { if (event.target === $("sheet")) closeSheet(); });
window.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (!$("sheet").hidden) closeSheet();
  else if (surfaces.current().name === "confirm" && !state.busy) handleUtterance("no");
});

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
setInterval(() => { checkAlerts().catch(() => {}); }, 10000);
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
