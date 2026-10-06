"use strict";

const $ = (id) => document.getElementById(id);
const state = { token: "", snapshot: null, selectedPlanId: null, busy: false };
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

function renderPlans(snapshot) {
  const container = $("plans");
  container.replaceChildren();
  const activeVersion = visibleVersion(snapshot);
  const plans = snapshot.plans.filter((plan) => plan.source_version === activeVersion);
  if (!plans.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "Run the investigation to see the options.";
    container.append(empty);
    return;
  }
  const approval = visibleApproval(snapshot);
  if (approval) {
    state.selectedPlanId = approval.plan_id;
  } else if (!plans.some((plan) => plan.id === state.selectedPlanId)) {
    state.selectedPlanId = plans.find((plan) => plan.kind === "split-express")?.id || plans[0].id;
  }
  for (const plan of plans) {
    const card = document.createElement("label");
    card.className = `plan${plan.id === state.selectedPlanId ? " selected" : ""}${plan.kind === "split-express" ? " recommended" : ""}`;
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
    if (plan.kind === "split-express") {
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = "Zero delay";
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

function renderControls() {
  const snapshot = state.snapshot;
  const approved = Boolean(snapshot && visibleApproval(snapshot));
  const executed = Boolean(snapshot?.executions.length);
  const hasCurrentPlan = Boolean(snapshot?.plans.some((plan) => plan.source_version === snapshot.source_version));
  $("investigate").disabled = state.busy || !snapshot || executed;
  $("approve").disabled = state.busy || !hasCurrentPlan || !state.selectedPlanId || approved || executed;
  $("execute").disabled = state.busy || !approved || executed;
  $("reset").disabled = state.busy;
  $("connect").disabled = state.busy;
}

function render(snapshot) {
  state.snapshot = snapshot;
  $("connection").textContent = "Connected";
  $("connection").className = "connection ready";
  $("incident-status").textContent = snapshot.state.status;
  $("stock-value").textContent = `${snapshot.state.inventory.arequipa.available} units`;
  const agentEvent = [...snapshot.events].reverse().find((event) =>
    event.name === "agent_investigation_completed" && event.data.source_version === visibleVersion(snapshot));
  const answer = $("agent-answer");
  answer.hidden = !agentEvent;
  if (agentEvent) {
    $("answer-text").textContent = agentEvent.data.answer;
    $("tool-summary").textContent = `${agentEvent.data.tool_trace.length} MCP calls · ${agentEvent.data.mode} mode · ${agentEvent.data.usage.outputTokens} output tokens`;
    $("agent-mode").textContent = agentEvent.data.mode;
  } else {
    $("agent-mode").textContent = "Agent";
  }
  renderPlans(snapshot);
  renderTimeline(snapshot.events);
  const execution = snapshot.executions[0];
  $("execution-state").textContent = execution ? "Operationally verified" : visibleApproval(snapshot) ? "Approved · ready" : "Waiting for approval";
  $("execution-result").hidden = !execution;
  if (execution) {
    const accounted = snapshot.state.shipment.units_on_delayed_route + execution.fulfillments.reduce((sum, item) => sum + item.units, 0);
    $("execution-result").textContent = `Verified: ${accounted} units accounted for · $${execution.incremental_cost_usd} extra · ${execution.notifications.length} simulated notifications. Customer delay: ${execution.projected_customer_delay_hours}h (projected).`;
  }
  renderControls();
}

async function refresh() { render(await request("/incidents/SHIP-421")); }

async function act(work, success) {
  setBusy(true);
  message("");
  try {
    await work();
    await refresh();
    message(success, true);
  } catch (error) {
    message(error.message || String(error));
    if (String(error.message).includes("Bearer")) {
      $("connection").textContent = "Token required";
      $("connection").className = "connection error";
    }
  } finally { setBusy(false); }
}

$("connect").addEventListener("click", () => {
  state.token = $("access-token").value.trim();
  act(refresh, "Connected to the incident.");
});
$("access-token").addEventListener("keydown", (event) => {
  if (event.key === "Enter") $("connect").click();
});
$("reset").addEventListener("click", () => act(async () => {
  await request("/demo/reset", "POST");
  state.selectedPlanId = null;
}, "Synthetic incident reset."));
$("investigate").addEventListener("click", () => act(
  () => request("/incidents/SHIP-421/agent/investigate", "POST", {}),
  "Investigation complete. Review the projected plans."
));
$("approve").addEventListener("click", () => act(async () => {
  const plan = state.snapshot.plans.find((item) => item.id === state.selectedPlanId);
  const approvedBy = $("approver").value.trim();
  if (!plan || !approvedBy) throw new Error("Select a plan and enter an approver name.");
  await request("/incidents/SHIP-421/approvals", "POST", {
    plan_id: plan.id, source_version: plan.source_version, approved_by: approvedBy,
  });
}, "The selected plan was approved by the operator."));
$("execute").addEventListener("click", () => act(async () => {
  const approval = visibleApproval(state.snapshot);
  await request("/incidents/SHIP-421/execute", "POST", {
    plan_id: approval.plan_id, source_version: approval.source_version,
  });
}, "Execution was operationally verified."));

act(refresh, "");
