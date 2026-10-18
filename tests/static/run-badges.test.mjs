import { test } from "node:test";
import assert from "node:assert/strict";
import { moduleUrl } from "./helpers.mjs";

const { checkBadge, checkNote, fallbackNote, traceSummary, executionSummary } = await import(moduleUrl("app/run-badges.js"));

test("badges and notes follow the grounding check and the budget fallback", () => {
  assert.equal(checkBadge({}), null);
  assert.deepEqual(checkBadge({ evaluations: [{ passed: true }], grounded: true }), { passed: true, text: "Checked against the data" });
  assert.deepEqual(checkBadge({ evaluations: [{}, {}], grounded: true }), { passed: true, text: "Checked against the data after one revision" });
  assert.deepEqual(checkBadge({ evaluations: [{ issues: ["$99 is not in the data"] }], grounded: false }),
    { passed: false, text: "Did not pass the data check: $99 is not in the data" });
  assert.match(checkNote({ evaluations: [{}], grounded: false }), /did not pass the automatic check/);
  assert.equal(checkNote({ evaluations: [{}], grounded: true }), null);
  assert.match(fallbackNote({ fallback: "daily_budget" }), /live model budget is used/);
  assert.equal(fallbackNote({ fallback: "sign_in" }), null);
});

test("summaries count calls, tokens and units", () => {
  assert.equal(traceSummary({ tool_trace: [1, 2, 3], mode: "replay", usage: { inputTokens: 0, outputTokens: 0 } }), "3 MCP calls · replay mode · 0 tokens");
  assert.equal(traceSummary({ tool_trace: [1], mode: "bedrock", fallback: "daily_budget", usage: { inputTokens: 10, outputTokens: 5 }, truncated: true }),
    "1 MCP call · bedrock mode · daily live budget used · 15 tokens · truncated");
  const snapshot = { state: { shipment: { units_on_delayed_route: 8 } } };
  const execution = { fulfillments: [{ units: 12 }], incremental_cost_usd: 120, notifications: [1, 2], projected_customer_delay_hours: 0 };
  assert.equal(executionSummary(snapshot, execution), "Verified: 20 units accounted for · $120 extra · 2 simulated notifications. Customer delay: 0h (projected).");
  assert.match(executionSummary(snapshot, { ...execution, accounted_units: 30 }), /^Verified: 30 units/);
});
