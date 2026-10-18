import { test } from "node:test";
import assert from "node:assert/strict";
import { moduleUrl } from "./helpers.mjs";

const {
  SURFACES, shortSpoken, homeCards, incidentFacts, displayPlan, confirmDetails, resultFigures, alertDetails, chipsFor, createSurfaces,
} = await import(moduleUrl("device/surfaces.js"));
const { cardTags } = await import(moduleUrl("device/carousel.js"));

const plans = [
  { id: "p-wait", kind: "wait", label: "Keep the delayed shipment", incremental_cost_usd: 0, projected_customer_delay_hours: 12, late_units: 20,
    orders: [{ order_id: "ORD-421", customer: "store", priority: "standard", delay_hours: 12 }], allocations: [{ source: "delayed-shipment", units: 20 }], source_version: 1 },
  { id: "p-express", kind: "split-express", label: "Fulfill local stock and send the rest express", incremental_cost_usd: 120, projected_customer_delay_hours: 0,
    orders: [{ order_id: "ORD-421", customer: "store", priority: "critical", delay_hours: 0 }],
    allocations: [{ source: "arequipa-stock", units: 12 }, { source: "express", units: 8 }], source_version: 1 },
];
const snapshot = {
  source_version: 1, plans, approvals: [], executions: [], bookings: [], events: [], preference: null,
  state: {
    incident_id: "SHIP-421", title: "Laptop shipment delayed in transit", status: "detected", kind: "delay",
    shipment: { origin: "Lima", destination: "Arequipa", sku: "LAPTOP-01", units_on_delayed_route: 20, original_eta: "2026-10-13T14:00:00-05:00", delayed_eta: "2026-10-14T02:00:00-05:00" },
    orders: [{ id: "ORD-421", quantity: 20, customer: "store", priority: "critical", due_eta: "2026-10-13T14:00:00-05:00" }],
    inventory: { arequipa: { available: 11 } },
  },
};
const inbox = [
  { incident_id: "SHIP-433", kind_label: "Carrier outage", priority: "critical", critical_units_at_risk: 12, status: "detected", title: "x", route: "Lima → Cusco", units: 30, due_eta: "2026-10-14T12:00:00-05:00" },
  { incident_id: "SHIP-421", kind_label: "Delayed in transit", priority: "standard", critical_units_at_risk: 0, status: "detected", title: "y", route: "Lima → Arequipa", units: 20, due_eta: "2026-10-13T14:00:00-05:00" },
];

test("the spoken line is short, and the home carousel starts with the briefing's pick", () => {
  assert.equal(shortSpoken("**Hello** there", null, (text) => text.replaceAll("*", "")), "Hello there");
  assert.equal(shortSpoken("ignored", "Spoken line"), "Spoken line");
  const long = shortSpoken("x".repeat(400));
  assert.equal(long.length, 260);
  assert.ok(long.endsWith("…"));
  assert.deepEqual(homeCards(inbox, "SHIP-421").map((card) => [card.incident_id, card.startHere]), [["SHIP-421", true], ["SHIP-433", false]]);
  assert.deepEqual(homeCards(inbox, null).map((card) => card.startHere), [false, false]);
  assert.deepEqual(SURFACES, ["home", "incident", "plans", "confirm", "receipt", "alert", "result"]);
});

test("incident facts and the plan on screen follow the execution, the approval, the selection or the pick", () => {
  const facts = incidentFacts(snapshot);
  assert.equal(facts.route, "Lima → Arequipa");
  assert.equal(facts.delayHours, 12);
  assert.deepEqual(facts.stock, { name: "Arequipa warehouse", available: 11 });
  assert.equal(facts.promiseLabel, "Customer promise");
  assert.equal(displayPlan(snapshot, null, plans[1]).id, "p-express");
  assert.equal(displayPlan(snapshot, "p-wait", plans[1]).id, "p-wait");
  assert.equal(displayPlan({ ...snapshot, approvals: [{ plan_id: "p-wait", source_version: 1 }] }, "p-express", plans[1]).id, "p-wait");
  assert.equal(displayPlan({ ...snapshot, executions: [{ plan_id: "p-express", source_version: 1 }] }, "p-wait", null).id, "p-express");
  assert.equal(displayPlan(null, null, null), null);
});

test("confirmation cards read back exactly what a yes would do", () => {
  const approval = confirmDetails({ kind: "approval", plan: plans[0] });
  assert.equal(approval.title, "Approve this plan?");
  assert.deepEqual(approval.figure, ["$0", "extra cost"]);
  assert.deepEqual(approval.rows, [["store", "+12 h late", "late"], ["Allocation", "20 via delayed shipment"]]);
  assert.deepEqual(confirmDetails({ kind: "approval", plan: plans[1] }).rows[0], ["store · critical", "On time", "on-time"]);
  assert.deepEqual(confirmDetails({ kind: "approval", plan: { ...plans[0], orders: [] } }).rows[0], ["Customer delay", "12 h"]);
  assert.equal(approval.warning, null);
  assert.equal(approval.yes, "Yes, approve");
  const late = confirmDetails({ kind: "approval", plan: { ...plans[0], orders: [{ ...plans[0].orders[0], priority: "critical" }] } });
  assert.equal(late.warning, "It leaves the critical order for store late.");
  const quote = { plan_label: plans[1].label, base_usd: 120, service_fee_usd: 5, tax_label: "Tax 18%", tax_usd: 22.5, total_usd: 147.5, payment_method: "Corporate card ending 4242 (simulated)" };
  const pay = confirmDetails({ kind: "purchase", purchase: { approve: true, quote }, plan: plans[1] });
  assert.equal(pay.title, "Approve and pay?");
  assert.deepEqual(pay.figure, ["$147.50", "total, charged once"]);
  assert.deepEqual(pay.rows.at(-1), ["Total", "$147.50"]);
  assert.equal(pay.note, "Charged once to the corporate card ending 4242. Nothing is charged until you say yes.");
  assert.equal(pay.yes, "Yes, approve and pay");
  assert.equal(confirmDetails({ kind: "purchase", purchase: { approve: false, quote }, plan: plans[1] }).yes, "Yes, pay");
});

test("the result card, the alert card and the chips come from the data", () => {
  const execution = { plan_id: "p-express", accounted_units: 20, incremental_cost_usd: 120, notifications: [1, 2], projected_customer_delay_hours: 0, fulfillments: [] };
  assert.deepEqual(resultFigures(snapshot, execution).map((item) => [item.label, item.value]),
    [["Units accounted for", "20"], ["Extra cost", "$120"], ["Notifications simulated", "2"], ["Customer delay", "0 h"]]);
  const alert = alertDetails({ incident_id: "SHIP-421", message: "Heads up.", approval_invalidated: true, new_plan: { label: "Reroute", incremental_cost_usd: 80, projected_customer_delay_hours: 3 } });
  assert.deepEqual(alert, { title: "Heads up on SHIP-421", text: "Heads up.", invalidated: true, plan: "Reroute · $80 · 3 h delay" });
  assert.equal(alertDetails({ incident_id: "SHIP-421", message: "Heads up on SHIP-421: Arequipa stock is now 20 units." }).text, "Arequipa stock is now 20 units.");
  const context = { snapshot, incidentId: "SHIP-421", inbox, plan: plans[1] };
  assert.deepEqual(chipsFor("home", context).map(([text]) => text), ["Any delays today?", "What's happening with SHIP-421?"]);
  assert.deepEqual(chipsFor("home", { ...context, pick: "SHIP-433" }).map(([text]) => text), ["Any delays today?", "What's happening with SHIP-433?"]);
  assert.deepEqual(chipsFor("home", { ...context, pick: "SHIP-999" }).map(([text]) => text), ["Any delays today?", "What's happening with SHIP-421?"]);
  assert.deepEqual(chipsFor("incident", context).map(([text]) => text), ["Show the plans", "Approve the recommended plan"]);
  assert.deepEqual(chipsFor("incident", { ...context, snapshot: { ...snapshot, plans: [] } }).map(([text]) => text), ["What's happening with SHIP-421?", "Any delays today?"]);
  assert.deepEqual(chipsFor("plans", context).map(([text]) => text), ["Approve the recommended plan", "Why this plan?", "Show the incident", "Book and pay"]);
  assert.deepEqual(chipsFor("plans", { ...context, plan: plans[0] }).map(([text]) => text), ["Approve the recommended plan", "Why this plan?", "Show the incident"]);
  const approved = { ...snapshot, approvals: [{ plan_id: "p-express", source_version: 1 }] };
  assert.deepEqual(chipsFor("plans", { ...context, snapshot: approved }).map(([text]) => text), ["Execute it", "Book and pay", "Why this plan?"]);
  const executed = { ...approved, executions: [{ plan_id: "p-express", source_version: 1 }], bookings: [{ plan_id: "p-express" }] };
  assert.deepEqual(chipsFor("result", { ...context, snapshot: executed }).map(([text]) => text), ["Any delays today?", "Next incident"]);
  assert.deepEqual(chipsFor("confirm", context), []);
  assert.deepEqual(chipsFor("plans", { ...context, snapshot: null }), []);
  for (const [, utterance] of chipsFor("plans", context)) assert.equal(typeof utterance, "string");
});

test("an inbox card carries at most two tags: start here, then risk or a critical order, then a state past detected", () => {
  const card = { startHere: true, critical_units_at_risk: 12, priority: "critical", status: "investigated" };
  assert.deepEqual(cardTags(card), [["start-here", "Start here"], ["at-risk", "12 critical units at risk"]]);
  assert.deepEqual(cardTags({ ...card, startHere: false }), [["at-risk", "12 critical units at risk"], ["state", "investigated"]]);
  assert.deepEqual(cardTags({ ...card, startHere: false, critical_units_at_risk: 0, status: "detected" }), [["critical", "Critical order"]]);
  assert.deepEqual(cardTags({ priority: "standard", critical_units_at_risk: 0, status: "detected" }), []);
});

test("a confirmation or an alert is dismissed back to the card underneath", () => {
  const surfaces = createSurfaces("home");
  assert.equal(surfaces.current().name, "home");
  surfaces.show("plans");
  surfaces.show("confirm", { kind: "approval", plan: plans[0] });
  assert.equal(surfaces.current().payload.plan.id, "p-wait");
  assert.equal(surfaces.show("dismiss").name, "plans");
  assert.equal(surfaces.show("dismiss").name, "plans");
  surfaces.show("confirm", {});
  surfaces.show("alert", {});
  assert.equal(surfaces.show("dismiss").name, "plans");
  surfaces.show("result");
  assert.equal(surfaces.show("dismiss").name, "result");
  const fresh = createSurfaces("incident");
  fresh.show("confirm", {});
  assert.equal(fresh.show("dismiss").name, "incident");
});
