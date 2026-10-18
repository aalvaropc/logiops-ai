import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { moduleUrl } from "./helpers.mjs";

const selectors = await import(moduleUrl("app/selectors.js"));
const intent = createRequire(import.meta.url)(path.resolve(path.dirname(new URL(import.meta.url).pathname), "..", "..", "logiops", "static", "intent.js"));

const plan = (id, kind, label, cost, delay, orders = [], allocations = [{ source: "delayed-shipment", units: 20 }]) =>
  ({ id: `SHIP-421:run:${kind}:v1`, kind, label, incremental_cost_usd: cost, projected_customer_delay_hours: delay, late_units: 0, orders, allocations, source_version: 1 });
const plans = [
  plan("a", "wait", "Keep the delayed shipment", 0, 12),
  plan("b", "reroute", "Move the full order to an alternative carrier", 80, 3),
  plan("c", "split-express", "Fulfill local stock and send the rest express", 120, 0, [], [{ source: "arequipa-stock", units: 12 }, { source: "express", units: 8 }]),
];
const snapshot = (overrides = {}) => ({ source_version: 1, plans, approvals: [], executions: [], events: [], state: { inventory: { arequipa: {} } }, ...overrides });

test("the visible version follows an execution and plans, approvals and the latest run come from it", () => {
  const executed = snapshot({ source_version: 2, executions: [{ source_version: 1 }], approvals: [{ source_version: 1, plan_id: "x" }, { source_version: 2 }],
    events: [{ name: "agent_investigation_completed", data: { source_version: 1, answer: "old" } }, { name: "agent_investigation_completed", data: { source_version: 2, answer: "new" } }] });
  assert.equal(selectors.visibleVersion(snapshot()), 1);
  assert.equal(selectors.visibleVersion(executed), 1);
  assert.equal(selectors.visibleApproval(executed).plan_id, "x");
  assert.equal(selectors.visiblePlans(executed).length, 3);
  assert.equal(selectors.latestAgentEvent(executed).data.answer, "old");
  assert.equal(selectors.localWarehouse(snapshot()), "arequipa");
  assert.equal(selectors.localWarehouse(snapshot({ state: { inventory: {} } })), null);
});

test("ranking puts critical delays first, then delay, late units and cost", () => {
  const critical = plan("d", "x", "x", 50, 1, [{ priority: "critical", delay_hours: 24 }]);
  assert.deepEqual(selectors.rankKey(critical), [24, 1, 0, 50]);
  assert.deepEqual([...plans, critical].sort(selectors.byRank).map((item) => item.kind), ["split-express", "reroute", "wait", "x"]);
  assert.equal(selectors.allocationSummary(plans[2]), "12 via arequipa stock · 8 via express");
});

test("the recommended plan follows the agent's answer, its label, or the ranking", () => {
  const answered = snapshot({ events: [{ name: "agent_investigation_completed", data: { source_version: 1, answer: "I recommend the wait.\nRecommended plan: SHIP-421:run:wait:v1" } }] });
  assert.equal(selectors.recommendedPlan(answered, intent).kind, "wait");
  const byLabel = snapshot({ events: [{ name: "agent_investigation_completed", data: { source_version: 1, answer: "Recommend Move the full order to an alternative carrier." } }] });
  assert.equal(selectors.recommendedPlan(byLabel, intent).kind, "reroute");
  assert.equal(selectors.recommendedPlan(snapshot(), intent).kind, "split-express");
  assert.equal(selectors.recommendedPlan(snapshot({ plans: [] }), intent), null);
});

test("an utterance names a plan by preference, price, cheapest, keyword or defaults to the pick", () => {
  const preferred = snapshot({ preference: { preferred_plan_id: plans[1].id } });
  assert.equal(selectors.planFromUtterance("approve my preference", preferred, intent).kind, "reroute");
  assert.equal(selectors.planFromUtterance("approve the cheapest plan", snapshot(), intent).kind, "wait");
  assert.equal(selectors.planFromUtterance("approve the $80 plan", snapshot(), intent).kind, "reroute");
  assert.equal(selectors.planFromUtterance("approve the $999 plan", snapshot(), intent), null);
  assert.equal(selectors.planFromUtterance("approve the split plan", snapshot(), intent).kind, "split-express");
  assert.equal(selectors.planFromUtterance("approve the recommended plan", snapshot(), intent).kind, "split-express");
  assert.deepEqual(selectors.namedPlanKinds("fly the hospital order and rebook the rest on ground"), ["priority-air-ground"]);
  assert.equal(selectors.namedPlanKinds("do the thing"), null);
});

test("event labels and dates read for people", () => {
  assert.equal(selectors.EVENT_LABELS.plan_approved, "Plan approved by operator");
  assert.equal(selectors.formatDate("2026-10-12T13:00:00-05:00"), "Oct 12, 01:00 PM");
});

test("the look-alike guard marks the words that set a plan apart from its nearest neighbour", () => {
  const labels = [
    "Wait for the booked carrier to restart", "Rebook both orders on an alternative ground carrier",
    "Fly the hospital order; the store order waits for the carrier", "Fly the hospital order; rebook the store order on ground",
  ];
  assert.deepEqual(selectors.distinguishing(labels[3], labels), ["Fly the hospital order;", "rebook the store order on ground", ""]);
  assert.deepEqual(selectors.distinguishing(labels[2], labels), ["Fly the hospital order;", "the store order waits for the carrier", ""]);
  assert.deepEqual(selectors.distinguishing(labels[0], labels), [labels[0]]);
  assert.deepEqual(selectors.distinguishing("Send the rest express", ["Send the rest by ground"]), ["Send the rest", "express", ""]);
  assert.deepEqual(selectors.distinguishing("Same plan", ["Same plan"]), ["Same plan"]);
  for (const label of labels) {
    const parts = selectors.distinguishing(label, labels).filter(Boolean);
    assert.equal(parts.join(" "), label);
  }
});
