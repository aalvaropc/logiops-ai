import { dollars } from "../app/purchase.js";
import { formatDate, allocationSummary, localWarehouse, visiblePlans, visibleApproval, plural } from "../app/selectors.js";

export const SPOKEN_LIMIT = 260;
export const SURFACES = ["home", "incident", "plans", "confirm", "receipt", "alert", "result"];
const TRANSIENT = new Set(["confirm", "alert"]);

export function stageLine(path) {
  const investigated = /\/incidents\/([^/]+)\/agent\/investigate$/.exec(path || "");
  if (investigated) return ["Asking the agent about", decodeURIComponent(investigated[1])];
  if (/\/agent\/briefing$/.test(path || "")) return ["Asking the agent about", "your queue"];
  return ["Asking the agent", ""];
}

export function stageCaption(run, seconds, live = false) {
  const calls = run.tool_trace?.length || 0;
  const count = `${calls} MCP ${plural(calls, "call")}`;
  if (run.mode === "replay") return ["Replayed from a recorded run", count, "scripted model"].join(" · ");
  return [live ? "Live from the MCP tool calls" : "Replayed from the recorded tool trace", count,
    Number.isFinite(seconds) ? `answered in ${seconds.toFixed(1)} s` : ""].filter(Boolean).join(" · ");
}

export function agentLine(run, check) {
  const calls = run?.tool_trace?.length || 0;
  if (!calls) return "";
  return [`${calls} MCP ${plural(calls, "call")} by the agent`, check?.text, run.mode === "replay" ? "scripted model" : ""].filter(Boolean).join(" · ");
}

const DECISION_LEAD = /^([A-Z]+-\d+) needs a decision\.\s*I recommend:\s*/;

export function shortSpoken(text, spoken, plain = (value) => value) {
  const line = String(spoken || plain(String(text || ""))).trim().replace(DECISION_LEAD, "$1: ");
  return line.length > SPOKEN_LIMIT ? `${line.slice(0, SPOKEN_LIMIT - 1).trimEnd()}…` : line;
}

export function homeCards(inbox, pick) {
  const cards = inbox.map((item) => ({ ...item, startHere: Boolean(pick) && item.incident_id === pick }));
  return [...cards.filter((card) => card.startHere), ...cards.filter((card) => !card.startHere)];
}

const isOpen = (item) => item.status !== "verified";

export function livePick(inbox, pick) {
  return inbox.some((item) => item.incident_id === pick && isOpen(item)) ? pick : null;
}

export function nextOpen(inbox, currentId) {
  return inbox.find((item) => isOpen(item) && item.incident_id !== currentId) || null;
}

const STATES = { investigated: "Investigated", approved: "Approved" };

export function cardTags(card) {
  if (card.status === "verified") return [["executed", "Executed"]];
  const tags = [];
  if (card.startHere) tags.push(["start-here", "Start here"]);
  if (card.critical_units_at_risk > 0) tags.push(["at-risk", `${card.critical_units_at_risk} critical units at risk`]);
  else if (card.priority === "critical") tags.push(["critical", "Critical order"]);
  if (STATES[card.status]) tags.push(["state", STATES[card.status]]);
  return tags.slice(0, 2);
}

export function criticalOutcome(plan) {
  const orders = plan?.orders || [];
  const critical = orders.filter((order) => order.priority === "critical");
  const counted = critical.length ? critical : orders;
  return {
    critical: critical.length > 0,
    onTime: counted.reduce((sum, order) => sum + order.quantity - (order.late_units || 0), 0),
    total: counted.reduce((sum, order) => sum + order.quantity, 0),
  };
}

function unitsOnTime(plan) {
  const { critical, onTime, total } = criticalOutcome(plan);
  const units = `${critical ? "critical " : ""}unit${total === 1 ? "" : "s"}`;
  return { allOnTime: onTime === total, text: `${onTime === total ? total : `${onTime} of ${total}`} ${units} projected on time` };
}

export function incidentBand(snapshot, summary) {
  const execution = snapshot.executions[0];
  const decided = execution?.plan_id || visibleApproval(snapshot)?.plan_id;
  const plan = decided && snapshot.plans.find((item) => item.id === decided);
  if (plan) {
    const { allOnTime, text } = unitsOnTime(plan);
    if (execution) return [allOnTime ? "ok" : "late", `Executed · ${text}`];
    return allOnTime ? ["warn", `Approved · ${text} once executed`] : ["late", `Approved · ${text}`];
  }
  if (!(summary?.critical_units_at_risk > 0)) return null;
  const pending = visiblePlans(snapshot).length ? " until a plan is approved" : "";
  return ["late", `${summary.critical_units_at_risk} critical units at risk${pending}`];
}

const capital = (name) => `${name[0].toUpperCase()}${name.slice(1)}`;

export function incidentFacts(snapshot) {
  const incident = snapshot.state;
  const shipment = incident.shipment;
  const units = incident.orders.reduce((sum, order) => sum + order.quantity, 0);
  const warehouse = localWarehouse(snapshot);
  return {
    id: incident.incident_id, title: incident.title, status: incident.status, kind: incident.kind,
    route: `${shipment.origin} → ${shipment.destination}`, units, sku: shipment.sku, orders: incident.orders.length,
    originalEta: formatDate(shipment.original_eta), delayedEta: formatDate(shipment.delayed_eta),
    delayHours: Math.round((Date.parse(shipment.delayed_eta) - Date.parse(shipment.original_eta)) / 3600000),
    promiseLabel: incident.orders.length === 1 ? "Customer promise" : "Shipment's original ETA",
    stock: warehouse ? { name: `${capital(warehouse)} warehouse`, available: incident.inventory[warehouse].available } : null,
  };
}

export const LIFECYCLE = ["Detected", "Investigated", "Approved", "Executed"];

export function lifecycleStep(snapshot) {
  if (!snapshot) return -1;
  if (snapshot.executions.length) return 3;
  if (visibleApproval(snapshot)) return 2;
  return visiblePlans(snapshot).length ? 1 : 0;
}

export function displayPlan(snapshot, selectedId, recommended) {
  if (!snapshot) return null;
  const plans = visiblePlans(snapshot);
  const execution = snapshot.executions[0];
  const wanted = execution?.plan_id || visibleApproval(snapshot)?.plan_id || selectedId || recommended?.id;
  return plans.find((plan) => plan.id === wanted) || snapshot.plans.find((plan) => plan.id === execution?.plan_id) || recommended || plans[0] || null;
}

function lateWarning(plan) {
  const late = (plan?.orders || []).filter((order) => order.priority === "critical" && order.delay_hours > 0);
  return late.length ? `It leaves the critical order for ${late.map((order) => order.customer).join(" and ")} late.` : null;
}

const delayText = (plan) => (plan.projected_customer_delay_hours ? `${plan.projected_customer_delay_hours} h` : "none");

export function orderRows(plan) {
  const orders = plan.orders || [];
  if (!orders.length) return [["Customer delay", delayText(plan)]];
  return orders.map((order) => [`${order.customer} · ${order.quantity} unit${order.quantity === 1 ? "" : "s"}${order.priority === "critical" ? " · critical order" : ""}`,
    order.delay_hours ? `+${order.delay_hours} h late` : "On time", order.delay_hours ? "late" : "on-time"]);
}

export function confirmDetails(payload) {
  if (payload.kind === "purchase") {
    const quote = payload.purchase.quote;
    const card = String(quote.payment_method).replace(/\s*\(simulated\)$/i, "").toLowerCase();
    return {
      kind: "purchase", title: payload.purchase.approve ? "Approve and pay?" : "Pay for the booking?", lead: quote.plan_label,
      figure: [dollars(quote.total_usd), "total, charged once"],
      rows: [["Carriers and services", dollars(quote.base_usd)], ["Service fee", dollars(quote.service_fee_usd)],
        [quote.tax_label, dollars(quote.tax_usd)], ["Total", dollars(quote.total_usd)]],
      note: `Charged once to the ${card} (simulated payment). Nothing is charged until you say yes.`, warning: lateWarning(payload.plan),
      yes: payload.purchase.approve ? "Yes, approve and pay" : "Yes, pay", no: "No",
    };
  }
  const plan = payload.plan;
  if (payload.kind === "withdraw") {
    return {
      kind: "withdraw", title: "Withdraw this approval?", lead: plan.label,
      figure: [`$${plan.incremental_cost_usd}`, "approved extra cost"],
      rows: [["Plans and approval", "cleared"], ["Incident data", "back to the original"], ["Next step", "investigate again"]],
      note: "An approval is recorded with its data, so withdrawing it resets the incident. Nothing has run yet.", warning: null,
      yes: "Yes, withdraw", no: "Keep it",
    };
  }
  return {
    kind: "approval", title: "Approve this plan?", lead: plan.label,
    figure: [`$${plan.incremental_cost_usd}`, "extra cost"],
    rows: [...orderRows(plan), ["Allocation", allocationSummary(plan)]],
    note: "Approval records the exact plan and data version. Nothing is executed yet.", warning: lateWarning(plan),
    yes: "Yes, approve", no: "No",
  };
}

export function resultFigures(snapshot, execution) {
  const accounted = execution.accounted_units
    ?? snapshot.state.shipment.units_on_delayed_route + execution.fulfillments.reduce((sum, item) => sum + item.units, 0);
  return [
    { label: "Units accounted for", value: String(accounted) },
    { label: "Extra cost", value: `$${execution.incremental_cost_usd}` },
    { label: "Notifications simulated", value: String(execution.notifications.length) },
    { label: "Customer delay", value: `${execution.projected_customer_delay_hours} h`, note: "projected" },
  ];
}

export function resultOutcome(plan) {
  const { critical, onTime, total } = criticalOutcome(plan);
  return {
    value: onTime === total ? String(total) : `${onTime} of ${total}`,
    label: `${critical ? "critical " : ""}unit${total === 1 ? "" : "s"} on time`, note: "projected",
  };
}

export function alertDetails(alert) {
  const plan = alert.new_plan;
  const before = alert.previous_plan;
  const invalidated = Boolean(alert.approval_invalidated);
  const change = alert.change ? `${capital(alert.change)}${invalidated ? ", so your approval no longer applies" : ", so the plans were recalculated"}.` : null;
  return {
    title: `Heads up on ${alert.incident_id}`, text: change || String(alert.message).replace(`Heads up on ${alert.incident_id}: `, ""),
    invalidated,
    was: before?.label ? { label: before.label, figures: Number.isFinite(before.incremental_cost_usd) ? `$${before.incremental_cost_usd}` : "" } : null,
    plan: plan ? {
      label: plan.label, figures: `$${plan.incremental_cost_usd} · ${plan.projected_customer_delay_hours ? `${plan.projected_customer_delay_hours} h late` : "on time"}`,
      late: plan.projected_customer_delay_hours > 0,
    } : null,
  };
}

export function chipsFor(surface, { snapshot, incidentId, inbox = [], plan = null, pick = null }) {
  const ask = (id) => [`What's happening with ${id}?`, `What's happening with ${id}, and which plan should we choose?`];
  const briefing = "Any delays today? What needs my attention first?";
  if (!snapshot) return [];
  const approved = Boolean(visibleApproval(snapshot));
  const executed = Boolean(snapshot.executions.length);
  const investigated = visiblePlans(snapshot).length > 0;
  const booked = (snapshot.bookings || []).some((booking) => plan && booking.plan_id === plan.id);
  const pay = plan && plan.incremental_cost_usd > 0 && !booked ? [["Book and pay", "Book and pay for the recommended plan", "act"]] : [];
  const approve = ["Approve the recommended plan", "Approve the recommended plan", "act"];
  const execute = ["Execute approved plan", "Execute the approved plan", "act"];
  const current = inbox.find((item) => item.incident_id === incidentId);
  const lead = livePick(inbox, pick) ?? (current && !isOpen(current) ? nextOpen(inbox, incidentId)?.incident_id : null) ?? incidentId;
  const next = nextOpen(inbox, incidentId);
  const openNext = next ? [[`Open ${next.incident_id}`, `Open ${next.incident_id}`]] : [];
  const result = [["See the result", "Show the result"]];
  const back = ["Back to queue", "Back to the queue"];
  switch (surface) {
    case "home": return [["Any delays today?", briefing], ask(lead)];
    case "incident":
      if (!investigated) return [ask(incidentId), back];
      if (executed) return [...result, ...openNext, back];
      return [...(approved ? [] : [approve]), ["Show the plans", "Show the plans"], back];
    case "plans":
      if (executed) return [...pay, back];
      if (approved) return [execute, ...pay, ["Why this plan?", "Why is that the recommended plan?"], back];
      return [approve, ["Why this plan?", "Why is that the recommended plan?"], ["Show the incident", "Show the incident"], ...pay, back];
    case "receipt":
      if (executed) return [...result, ...openNext, back];
      return approved ? [execute, back] : [back];
    case "alert": return [["Approve the new pick", "Approve the recommended plan", "act"], ["Why did it change?", "Why did the recommended plan change?"]];
    case "result": return [...pay, ...openNext, back];
    default: return [];
  }
}

export function createSurfaces(initial = "home") {
  let current = { name: initial, payload: {} };
  let previous = null;
  return {
    current: () => current,
    show(name, payload = {}) {
      if (name === "dismiss") {
        if (TRANSIENT.has(current.name)) current = previous || { name: "incident", payload: {} };
        previous = null;
        return current;
      }
      if (TRANSIENT.has(name)) {
        if (!TRANSIENT.has(current.name)) previous = current;
      } else {
        previous = null;
      }
      current = { name, payload };
      return current;
    },
  };
}
