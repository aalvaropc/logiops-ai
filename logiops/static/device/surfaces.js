import { dollars } from "../app/purchase.js";
import { formatDate, allocationSummary, localWarehouse, visiblePlans, visibleApproval } from "../app/selectors.js";

export const SPOKEN_LIMIT = 260;
export const SURFACES = ["home", "incident", "plans", "confirm", "receipt", "alert", "result"];
const TRANSIENT = new Set(["confirm", "alert"]);

export function shortSpoken(text, spoken, plain = (value) => value) {
  const line = String(spoken || plain(String(text || ""))).trim();
  return line.length > SPOKEN_LIMIT ? `${line.slice(0, SPOKEN_LIMIT - 1).trimEnd()}…` : line;
}

export function homeCards(inbox, pick) {
  const cards = inbox.map((item) => ({ ...item, startHere: Boolean(pick) && item.incident_id === pick }));
  return [...cards.filter((card) => card.startHere), ...cards.filter((card) => !card.startHere)];
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
  return orders.map((order) => [`${order.customer}${order.priority === "critical" ? " · critical" : ""}`,
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
      note: `Charged once to the ${card}. Nothing is charged until you say yes.`, warning: lateWarning(payload.plan),
      yes: payload.purchase.approve ? "Yes, approve and pay" : "Yes, pay", no: "No",
    };
  }
  const plan = payload.plan;
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

export function alertDetails(alert) {
  const plan = alert.new_plan;
  return {
    title: `Heads up on ${alert.incident_id}`, text: String(alert.message).replace(`Heads up on ${alert.incident_id}: `, ""),
    invalidated: Boolean(alert.approval_invalidated),
    plan: plan ? `${plan.label} · $${plan.incremental_cost_usd} · ${plan.projected_customer_delay_hours} h delay` : null,
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
  const pay = plan && plan.incremental_cost_usd > 0 && !booked ? [["Book and pay", "Book and pay for the recommended plan"]] : [];
  const lead = inbox.some((item) => item.incident_id === pick) ? pick : incidentId;
  switch (surface) {
    case "home": return [["Any delays today?", briefing], ask(lead)];
    case "incident":
      if (!investigated) return [ask(incidentId), ["Any delays today?", briefing]];
      return [["Show the plans", "Show the plans"], ...(approved || executed ? [] : [["Approve the recommended plan", "Approve the recommended plan"]])];
    case "plans":
      if (executed) return [...pay, ["Any delays today?", briefing]];
      if (approved) return [["Execute it", "Execute the approved plan"], ...pay, ["Why this plan?", "Why is that the recommended plan?"]];
      return [["Approve the recommended plan", "Approve the recommended plan"], ["Why this plan?", "Why is that the recommended plan?"],
        ["Show the incident", "Show the incident"], ...pay];
    case "receipt": return approved && !executed ? [["Execute it", "Execute the approved plan"]] : [["Any delays today?", briefing]];
    case "alert": return [["Approve the new pick", "Approve the recommended plan"], ["Why did it change?", "Why did the recommended plan change?"]];
    case "result": return [...pay, ["Any delays today?", briefing], inbox.length > 1 ? ["Next incident", "start over"] : null].filter(Boolean);
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
