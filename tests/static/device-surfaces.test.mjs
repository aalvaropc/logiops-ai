import { test } from "node:test";
import assert from "node:assert/strict";
import { moduleUrl } from "./helpers.mjs";

const {
  SURFACES, shortSpoken, homeCards, incidentFacts, displayPlan, confirmDetails, resultFigures, alertDetails, chipsFor, createSurfaces,
  lifecycleStep, LIFECYCLE, cardTags, resultOutcome, livePick, nextOpen, criticalOutcome, incidentBand, stageLine, stageCaption, agentLine,
} = await import(moduleUrl("device/surfaces.js"));

const plans = [
  { id: "p-wait", kind: "wait", label: "Keep the delayed shipment", incremental_cost_usd: 0, projected_customer_delay_hours: 12, late_units: 20,
    orders: [{ order_id: "ORD-421", customer: "store", priority: "standard", quantity: 20, delay_hours: 12, late_units: 20 }], allocations: [{ source: "delayed-shipment", units: 20 }], source_version: 1 },
  { id: "p-express", kind: "split-express", label: "Fulfill local stock and send the rest express", incremental_cost_usd: 120, projected_customer_delay_hours: 0,
    orders: [{ order_id: "ORD-421", customer: "store", priority: "critical", quantity: 20, delay_hours: 0, late_units: 0 }],
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

test("the spoken line is short, and the home queue starts with the briefing's pick", () => {
  assert.equal(shortSpoken("**Hello** there", null, (text) => text.replaceAll("*", "")), "Hello there");
  assert.equal(shortSpoken("ignored", "Spoken line"), "Spoken line");
  assert.equal(shortSpoken("", "SHIP-433 needs a decision. I recommend: Fly the hospital order."), "SHIP-433: Fly the hospital order.");
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
  assert.deepEqual(approval.rows, [["store · 20 units", "+12 h late", "late"], ["Allocation", "20 via delayed shipment"]]);
  assert.deepEqual(confirmDetails({ kind: "approval", plan: plans[1] }).rows[0], ["store · 20 units · critical order", "On time", "on-time"]);
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
  assert.equal(pay.note, "Charged once to the corporate card ending 4242 (simulated payment). Nothing is charged until you say yes.");
  const withdraw = confirmDetails({ kind: "withdraw", plan: plans[1] });
  assert.deepEqual([withdraw.title, withdraw.lead, withdraw.yes, withdraw.no], ["Withdraw this approval?", plans[1].label, "Yes, withdraw", "Keep it"]);
  assert.equal(pay.yes, "Yes, approve and pay");
  assert.equal(confirmDetails({ kind: "purchase", purchase: { approve: false, quote }, plan: plans[1] }).yes, "Yes, pay");
});

test("the result card, the alert card and the chips come from the data", () => {
  const execution = { plan_id: "p-express", accounted_units: 20, incremental_cost_usd: 120, notifications: [1, 2], projected_customer_delay_hours: 0, fulfillments: [] };
  assert.deepEqual(resultFigures(snapshot, execution).map((item) => [item.label, item.value]),
    [["Units accounted for", "20"], ["Extra cost", "$120"], ["Notifications simulated", "2"], ["Customer delay", "0 h"]]);
  assert.deepEqual(resultOutcome(plans[1]), { value: "20", label: "critical units on time", note: "projected" });
  assert.deepEqual(resultOutcome(plans[0]), { value: "0 of 20", label: "units on time", note: "projected" });
  const alert = alertDetails({ incident_id: "SHIP-421", message: "Heads up.", approval_invalidated: true, previous_plan: { label: "Wait", incremental_cost_usd: 0 },
    new_plan: { label: "Reroute", incremental_cost_usd: 80, projected_customer_delay_hours: 3 } });
  assert.deepEqual(alert, { title: "Heads up on SHIP-421", text: "Heads up.", invalidated: true, was: { label: "Wait", figures: "$0" },
    plan: { label: "Reroute", figures: "$80 · 3 h late", late: true } });
  assert.equal(alertDetails({ incident_id: "SHIP-421", message: "x", change: "local stock is now 3 units", approval_invalidated: true }).text,
    "Local stock is now 3 units, so your approval no longer applies.");
  assert.deepEqual(alertDetails({ incident_id: "SHIP-421", message: "x", new_plan: { label: "Ship", incremental_cost_usd: 0, projected_customer_delay_hours: 0 } }).plan,
    { label: "Ship", figures: "$0 · on time", late: false });
  assert.deepEqual(alertDetails({ incident_id: "SHIP-421", message: "x", previous_plan: { label: "Wait" } }).was, { label: "Wait", figures: "" });
  assert.equal(alertDetails({ incident_id: "SHIP-421", message: "Heads up on SHIP-421: Arequipa stock is now 20 units." }).text, "Arequipa stock is now 20 units.");
  const context = { snapshot, incidentId: "SHIP-421", inbox, plan: plans[1] };
  assert.deepEqual(chipsFor("home", context).map(([text]) => text), ["Any delays today?", "What's happening with SHIP-421?"]);
  assert.deepEqual(chipsFor("home", { ...context, pick: "SHIP-433" }).map(([text]) => text), ["Any delays today?", "What's happening with SHIP-433?"]);
  assert.deepEqual(chipsFor("home", { ...context, pick: "SHIP-999" }).map(([text]) => text), ["Any delays today?", "What's happening with SHIP-421?"]);
  assert.deepEqual(chipsFor("incident", context).map(([text]) => text), ["Approve the recommended plan", "Show the plans", "Back to queue"]);
  assert.deepEqual(chipsFor("plans", context).filter(([, , kind]) => kind === "act").map(([text]) => text), ["Approve the recommended plan"]);
  assert.deepEqual(chipsFor("alert", context)[0], ["Approve the new pick", "Approve the recommended plan", "act"]);
  assert.deepEqual(chipsFor("incident", { ...context, snapshot: { ...snapshot, plans: [] } }).map(([text]) => text), ["What's happening with SHIP-421?", "Back to queue"]);
  assert.deepEqual(chipsFor("plans", context).map(([text]) => text), ["Approve the recommended plan", "Why this plan?", "Show the incident", "Back to queue"]);
  assert.deepEqual(chipsFor("plans", { ...context, plan: plans[0] }).map(([text]) => text), ["Approve the recommended plan", "Why this plan?", "Show the incident", "Back to queue"]);
  const approved = { ...snapshot, approvals: [{ plan_id: "p-express", source_version: 1 }] };
  assert.deepEqual(chipsFor("plans", { ...context, snapshot: approved }).map(([text]) => text), ["Execute approved plan", "Book and pay", "Why this plan?", "Back to queue"]);
  assert.deepEqual(chipsFor("plans", { ...context, snapshot: approved })[0], ["Execute approved plan", "Execute the approved plan", "act"]);
  const free = { ...context, plan: plans[0] };
  const approvedFree = { ...snapshot, approvals: [{ plan_id: "p-wait", source_version: 1 }] };
  assert.deepEqual(chipsFor("plans", { ...free, snapshot: approvedFree }).map(([text]) => text), ["Execute approved plan", "Why this plan?", "Back to queue"], "a $0 plan has nothing to book");
  assert.deepEqual(chipsFor("plans", { ...free, snapshot: { ...approvedFree, executions: [{ plan_id: "p-wait", source_version: 1 }] } }).map(([text]) => text), ["Back to queue"]);
  assert.deepEqual(chipsFor("plans", { ...context, snapshot: { ...approved, executions: [{ plan_id: "p-express", source_version: 1 }] } }).map(([text]) => text), ["Book and pay", "Back to queue"]);
  const executed = { ...approved, executions: [{ plan_id: "p-express", source_version: 1 }], bookings: [{ plan_id: "p-express" }] };
  assert.deepEqual(chipsFor("result", { ...context, snapshot: executed }).map(([text]) => text), ["Open SHIP-433", "Back to queue"]);
  assert.deepEqual(chipsFor("result", { ...context, snapshot: executed }).find(([text]) => text === "Open SHIP-433")[1], "Open SHIP-433");
  const resolved = inbox.map((item) => ({ ...item, status: "verified" }));
  assert.deepEqual(chipsFor("result", { ...context, snapshot: executed, inbox: resolved }).map(([text]) => text), ["Back to queue"]);
  assert.deepEqual(chipsFor("receipt", { ...context, snapshot: executed }).map(([text]) => text), ["See the result", "Open SHIP-433", "Back to queue"]);
  assert.deepEqual(chipsFor("receipt", { ...context, snapshot: approved }).map(([text]) => text), ["Execute approved plan", "Back to queue"]);
  assert.deepEqual(chipsFor("incident", { ...context, snapshot: executed }).map(([text]) => text), ["See the result", "Open SHIP-433", "Back to queue"]);
  const doneHere = [{ ...inbox[0], status: "verified" }, inbox[1]];
  assert.deepEqual(chipsFor("home", { ...context, incidentId: "SHIP-433", inbox: doneHere, pick: "SHIP-433" }).map(([text]) => text),
    ["Any delays today?", "What's happening with SHIP-421?"]);
  assert.deepEqual(chipsFor("confirm", context), []);
  assert.deepEqual(chipsFor("plans", { ...context, snapshot: null }), []);
  for (const [, utterance] of chipsFor("plans", context)) assert.equal(typeof utterance, "string");
  assert.deepEqual(chipsFor("result", { ...context, snapshot: executed }).at(-1), ["Back to queue", "Back to the queue"]);
});

test("an inbox card carries at most two tags: start here, then risk or a critical order, then a state past detected", () => {
  const card = { startHere: true, critical_units_at_risk: 12, priority: "critical", status: "investigated" };
  assert.deepEqual(cardTags(card), [["start-here", "Start here"], ["at-risk", "12 critical units at risk"]]);
  assert.deepEqual(cardTags({ ...card, startHere: false }), [["at-risk", "12 critical units at risk"], ["state", "Investigated"]]);
  assert.deepEqual(cardTags({ ...card, startHere: false, critical_units_at_risk: 0, status: "approved" }), [["critical", "Critical order"], ["state", "Approved"]]);
  assert.deepEqual(cardTags({ ...card, critical_units_at_risk: 0, status: "verified" }), [["executed", "Executed"]]);
  assert.deepEqual(cardTags({ ...card, startHere: false, critical_units_at_risk: 0, status: "detected" }), [["critical", "Critical order"]]);
  assert.deepEqual(cardTags({ priority: "standard", critical_units_at_risk: 0, status: "detected" }), []);
});

test("the lifecycle strip follows detection, investigation, approval and execution", () => {
  assert.equal(lifecycleStep(null), -1);
  assert.equal(lifecycleStep({ ...snapshot, plans: [] }), 0);
  assert.equal(lifecycleStep(snapshot), 1);
  assert.equal(lifecycleStep({ ...snapshot, approvals: [{ plan_id: "p-express", source_version: 1 }] }), 2);
  assert.equal(lifecycleStep({ ...snapshot, executions: [{ plan_id: "p-express", source_version: 1 }] }), 3);
  assert.deepEqual(LIFECYCLE, ["Detected", "Investigated", "Approved", "Executed"]);
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

test("an executed incident drops out of the briefing's pick and the queue moves on", () => {
  const done = [{ ...inbox[0], status: "verified" }, inbox[1]];
  assert.equal(livePick(inbox, "SHIP-433"), "SHIP-433");
  assert.equal(livePick(done, "SHIP-433"), null);
  assert.equal(livePick(inbox, "SHIP-999"), null);
  assert.equal(nextOpen(inbox, "SHIP-433").incident_id, "SHIP-421");
  assert.equal(nextOpen(done, "SHIP-421"), null);
  assert.equal(nextOpen(done, null).incident_id, "SHIP-421");
});

test("the incident band follows the approved or executed plan, not the risk it had at detection", () => {
  const orders = [{ order_id: "A", customer: "hospital", priority: "critical", quantity: 12, delay_hours: 0, late_units: 0 },
    { order_id: "B", customer: "store", priority: "standard", quantity: 18, delay_hours: 8, late_units: 18 }];
  const fly = { id: "p-fly", label: "Fly the critical order", source_version: 1, orders };
  const slow = { id: "p-slow", label: "Wait", source_version: 1, orders: orders.map((order) => ({ ...order, delay_hours: 8, late_units: order.quantity })) };
  const base = { ...snapshot, plans: [fly, slow] };
  assert.deepEqual(criticalOutcome(fly), { critical: true, onTime: 12, total: 12 });
  assert.deepEqual(criticalOutcome({ orders: [orders[1]] }), { critical: false, onTime: 0, total: 18 });
  assert.equal(incidentBand(base), null);
  const approve = (id) => ({ ...base, approvals: [{ plan_id: id, source_version: 1 }] });
  assert.deepEqual(incidentBand(approve("p-fly")), ["warn", "Approved · 12 critical units projected on time once executed"]);
  assert.deepEqual(incidentBand(approve("p-slow")), ["late", "Approved · 0 of 12 critical units projected on time"]);
  const executed = { ...approve("p-fly"), executions: [{ plan_id: "p-fly", source_version: 1 }] };
  assert.deepEqual(incidentBand(executed), ["ok", "Executed · 12 critical units projected on time"]);
  const standard = { ...base, plans: [{ ...fly, orders: [{ ...orders[1], delay_hours: 0, late_units: 0 }] }], executions: [{ plan_id: "p-fly", source_version: 1 }] };
  assert.deepEqual(incidentBand(standard), ["ok", "Executed · 18 units projected on time"]);
});

test("the agent stage names who is asked and captions the recorded trace honestly", () => {
  assert.deepEqual(stageLine("/incidents/SHIP-433/agent/investigate"), ["Asking the agent about", "SHIP-433"]);
  assert.deepEqual(stageLine("/agent/briefing"), ["Asking the agent about", "your queue"]);
  assert.deepEqual(stageLine("/incidents/SHIP-433/agent/ask"), ["Asking the agent", ""]);
  const run = { tool_trace: [{ tool: "get_shipment" }, { tool: "investigate_incident" }], mode: "replay" };
  assert.equal(stageCaption(run, 13.04), "Replayed from a recorded run · 2 MCP calls · scripted model");
  assert.equal(stageCaption(run, 3.14, true), "Replayed from a recorded run · 2 MCP calls · scripted model");
  const bedrock = { tool_trace: [{ tool: "list_incidents" }], mode: "bedrock" };
  assert.equal(stageCaption(bedrock, null), "Replayed from the recorded tool trace · 1 MCP call");
  assert.equal(stageCaption(bedrock, 13.04, true), "Live from the MCP tool calls · 1 MCP call · answered in 13.0 s");
  assert.equal(agentLine(run, { passed: true, text: "Checked against the data" }), "2 MCP calls by the agent · Checked against the data · scripted model");
  assert.equal(agentLine({ tool_trace: [], mode: "bedrock" }, null), "");
  assert.equal(agentLine(undefined, null), "");
});
