"use strict";

const $ = (id) => document.getElementById(id);
const state = { token: "", snapshot: null, selectedPlanId: null, busy: false, conversation: [], speaking: false };
const eventLabels = {
  scenario_reset: "Synthetic incident reset",
  incident_investigated: "MCP investigation completed",
  agent_investigation_completed: "Agent assessment recorded",
  plan_approved: "Plan approved by operator",
  plan_executed: "Fulfillment plan executed",
  notifications_simulated: "Notifications simulated",
  execution_verified: "All units accounted for",
  inventory_changed: "Local inventory changed",
};
const planKeywords = [
  ["split-express", /\b(split|express)\b/],
  ["reroute", /\b(reroute|re-route|economy)\b/],
  ["wait", /\bwait\b/],
];

function message(text, success = false) {
  const box = $("message");
  box.textContent = text;
  box.className = text ? `message visible${success ? " success" : ""}` : "message";
}

function setBusy(busy) {
  state.busy = busy;
  renderControls();
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
    throw new Error(detail);
  }
  return response.json();
}

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

// The plan the agent recommended: an exact plan ID in its answer, then a label,
// then the lowest projected delay and cost as a deterministic fallback.
function recommendedPlan(snapshot) {
  const plans = visiblePlans(snapshot);
  if (!plans.length) return null;
  const answer = (latestAgentEvent(snapshot)?.data.answer || "").toLowerCase();
  return plans.find((plan) => answer.includes(plan.id.toLowerCase()))
    || plans.find((plan) => answer.includes(`recommend ${plan.label.toLowerCase()}`))
    || [...plans].sort((a, b) =>
      a.projected_customer_delay_hours - b.projected_customer_delay_hours
      || a.incremental_cost_usd - b.incremental_cost_usd)[0];
}

function renderPlans(snapshot) {
  const container = $("plans");
  container.replaceChildren();
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
    if (isRecommended) badges.push("Agent pick");
    if (plan.projected_customer_delay_hours === 0) badges.push("Zero delay");
    for (const text of badges) {
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = text;
      title.append(badge);
    }
    const allocation = document.createElement("small");
    allocation.textContent = plan.allocations.map((item) => `${item.units} via ${item.source.replaceAll("-", " ")}`).join(" · ");
    description.append(title, allocation);
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

function renderConversation() {
  const list = $("conversation");
  list.replaceChildren();
  const entries = state.conversation.length ? state.conversation : [{
    role: "assistant",
    text: "Hi, I'm LogiOps. Ask me what's happening with SHIP-421, and I'll investigate it with the MCP tools.",
  }];
  for (const entry of entries) {
    const item = document.createElement("li");
    item.className = `turn ${entry.role}`;
    const who = document.createElement("span");
    who.className = "turn-role";
    who.textContent = entry.role === "user" ? "You" : "LogiOps";
    const text = document.createElement("p");
    text.textContent = entry.text;
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

function say(role, text, meta) {
  state.conversation.push({ role, text, meta });
  renderConversation();
  if (role === "assistant" && $("speak-replies").checked && "speechSynthesis" in window) {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
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
  $("execute").disabled = state.busy || !approved || executed;
  $("reset").disabled = state.busy;
  $("set-stock").disabled = state.busy || !snapshot || executed;
  $("connect").disabled = state.busy;
}

function render(snapshot) {
  state.snapshot = snapshot;
  $("connection").textContent = "Connected";
  $("connection").className = "connection ready";
  $("incident-status").textContent = snapshot.state.status;
  $("stock-value").textContent = `${snapshot.state.inventory.arequipa.available} units`;
  const shipment = snapshot.state.shipment;
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
  renderPlans(snapshot);
  renderTimeline(snapshot.events);
  const execution = snapshot.executions[0];
  $("execution-state").textContent = execution ? "Operationally verified" : visibleApproval(snapshot) ? "Approved · ready" : "Waiting for approval";
  $("execution-result").hidden = !execution;
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
  const accounted = snapshot.state.shipment.units_on_delayed_route + execution.fulfillments.reduce((sum, item) => sum + item.units, 0);
  return `Verified: ${accounted} units accounted for · $${execution.incremental_cost_usd} extra · ${execution.notifications.length} simulated notifications. Customer delay: ${execution.projected_customer_delay_hours}h (projected).`;
}

async function refresh() { render(await request("/incidents/SHIP-421")); }

async function act(work, success) {
  setBusy(true);
  message("");
  try {
    await work();
    await refresh();
    if (success) message(success, true);
  } catch (error) {
    message(error.message || String(error));
    if (String(error.message).includes("Bearer")) {
      $("connection").textContent = "Token required";
      $("connection").className = "connection error";
    }
    throw error;
  } finally { setBusy(false); }
}

async function approvePlan(plan) {
  const approvedBy = $("approver").value.trim();
  if (!plan || !approvedBy) throw new Error("Select a plan and enter an approver name.");
  await request("/incidents/SHIP-421/approvals", "POST", {
    plan_id: plan.id, source_version: plan.source_version, approved_by: approvedBy,
  });
}

async function executeApproved() {
  const approval = visibleApproval(state.snapshot);
  if (!approval) throw new Error("No plan is approved for the current incident version.");
  await request("/incidents/SHIP-421/execute", "POST", {
    plan_id: approval.plan_id, source_version: approval.source_version,
  });
}

function planFromUtterance(text) {
  const plans = visiblePlans(state.snapshot);
  for (const [kind, pattern] of planKeywords) {
    if (pattern.test(text)) return plans.find((plan) => plan.kind === kind);
  }
  return recommendedPlan(state.snapshot);
}

// A thin intent layer, like an Alexa+ action: approval and execution go through the
// same REST endpoints as the buttons; anything else is a question for the agent.
async function handleUtterance(raw) {
  const text = raw.trim();
  if (!text || state.busy) return;
  say("user", text);
  const lower = text.toLowerCase();
  try {
    if (/\b(reset|start over)\b/.test(lower)) {
      await act(() => request("/demo/reset", "POST"), "");
      state.selectedPlanId = null;
      say("assistant", "Done. SHIP-421 is back to its original delayed state.");
    } else if (/\bapprove\b/.test(lower)) {
      if (!visiblePlans(state.snapshot).length) {
        say("assistant", "There are no plans for the current data yet. Ask me to investigate first.");
        return;
      }
      const plan = planFromUtterance(lower);
      await act(() => approvePlan(plan), "");
      say("assistant", `Approved “${plan.label}” for version ${plan.source_version}: ${plan.projected_customer_delay_hours} hours of delay, $${plan.incremental_cost_usd} extra. Say “execute it” when you're ready.`);
    } else if (/\b(execute|go ahead|do it|run it)\b/.test(lower) || (/^yes\b/.test(lower) && visibleApproval(state.snapshot))) {
      await act(executeApproved, "");
      const execution = state.snapshot.executions[0];
      say("assistant", `The plan was executed. ${executionSummary(state.snapshot, execution)} Delivery is projected, not physically confirmed.`);
    } else {
      // Follow-ups reuse the latest investigation of the data on screen; anything that
      // asks to (re)investigate, or arrives after the data changed, runs a fresh one.
      const current = latestAgentEvent(state.snapshot);
      const stale = !current || current.data.source_version !== visibleVersion(state.snapshot);
      const fresh = stale || /\b(investigate|re-?check|refresh|start again|what(?:'s| is) happening)\b/.test(lower);
      const history = state.conversation.slice(0, -1).slice(-6).map(({ role, text: turn }) => ({ role, text: turn.slice(0, 1000) }));
      let run;
      await act(async () => {
        run = fresh
          ? await request("/incidents/SHIP-421/agent/investigate", "POST", { question: text })
          : await request("/incidents/SHIP-421/agent/ask", "POST", { question: text, history });
      }, "");
      say("assistant", run.answer, `${fresh ? "investigation" : "follow-up"} · ${traceSummary(run)}`);
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
  act(refresh, "Connected to the incident.").catch(() => {});
});
$("access-token").addEventListener("keydown", (event) => {
  if (event.key === "Enter") $("connect").click();
});
$("reset").addEventListener("click", () => act(async () => {
  await request("/demo/reset", "POST");
  state.selectedPlanId = null;
  state.conversation = [];
}, "Synthetic incident reset.").catch(() => {}));
$("set-stock").addEventListener("click", () => act(async () => {
  const available = Number.parseInt($("stock-input").value, 10);
  if (!Number.isInteger(available) || available < 0) throw new Error("Enter a whole number of units.");
  await request("/demo/inventory", "POST", { available });
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
act(refresh, "").catch(() => {});
