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
  assert.equal(checkBadge({ evaluations: [{ issues: ["These times do not match the incident's data or any plan (Lima time): Oct 12, 16:00."] }], grounded: false }).text,
    "Did not pass the data check: These times do not match the incident's data or any plan (local time): Oct 12, 16:00.");
  assert.match(checkNote({ evaluations: [{}], grounded: false }), /did not pass the automatic check/);
  assert.equal(checkNote({ evaluations: [{}], grounded: true }), null);
  assert.match(fallbackNote({ fallback: "daily_budget" }), /live model budget is used/);
  assert.match(fallbackNote({ fallback: "model_unavailable" }), /live model is unavailable right now/);
  assert.match(fallbackNote({ fallback: "sign_in" }), /You're a guest, so answers come from the scripted replay\. Press Link account/);
  assert.match(fallbackNote({ fallback: "guest_budget" }), /live answers open to guests today are used/);
  assert.equal(fallbackNote({ fallback: "something_else" }), null);
  assert.equal(fallbackNote({}), null);
});

test("summaries count calls, tokens and units", () => {
  assert.equal(traceSummary({ tool_trace: [1, 2, 3], mode: "replay", usage: { inputTokens: 0, outputTokens: 0 } }), "3 MCP calls · replay mode · 0 tokens");
  assert.equal(traceSummary({ tool_trace: [1], mode: "bedrock", fallback: "daily_budget", usage: { inputTokens: 10, outputTokens: 5 }, truncated: true }),
    "1 MCP call · bedrock mode · daily live budget used · 15 tokens · truncated");
  assert.equal(traceSummary({ tool_trace: [1, 2], mode: "replay", fallback: "model_unavailable", usage: {} }),
    "2 MCP calls · replay mode · live model unavailable · 0 tokens");
  assert.equal(traceSummary({ tool_trace: [1], mode: "replay", fallback: "sign_in", usage: {} }), "1 MCP call · replay mode · guest on the replay · 0 tokens");
  assert.equal(traceSummary({ tool_trace: [1], mode: "replay", fallback: "guest_budget", usage: {} }), "1 MCP call · replay mode · guest share used · 0 tokens");
  const snapshot = { state: { shipment: { units_on_delayed_route: 8 } } };
  const execution = { fulfillments: [{ units: 12 }], incremental_cost_usd: 120, notifications: [1, 2], projected_customer_delay_hours: 0 };
  assert.equal(executionSummary(snapshot, execution), "Verified: 20 units accounted for · $120 extra · 2 simulated notifications. Customer delay: 0h (projected).");
  assert.match(executionSummary(snapshot, { ...execution, accounted_units: 30 }), /^Verified: 30 units/);
});
