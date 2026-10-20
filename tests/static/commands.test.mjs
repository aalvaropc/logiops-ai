import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { moduleUrl } from "./helpers.mjs";

const { createCommands, approvalReadback } = await import(moduleUrl("app/commands.js"));
const { CAPABILITIES_TEXT, CAPABILITIES_SPOKEN } = await import(moduleUrl("app/capabilities.js"));
const { createStore } = await import(moduleUrl("app/store.js"));
const selectors = await import(moduleUrl("app/selectors.js"));
const badges = await import(moduleUrl("app/run-badges.js"));
const intent = createRequire(import.meta.url)(path.resolve(path.dirname(new URL(import.meta.url).pathname), "..", "..", "logiops", "static", "intent.js"));

const plans = [
  { id: "SHIP-421:r:wait:v1", kind: "wait", label: "Keep the delayed shipment", incremental_cost_usd: 0, projected_customer_delay_hours: 12, late_units: 20, orders: [], allocations: [], source_version: 1 },
  { id: "SHIP-421:r:reroute:v1", kind: "reroute", label: "Move the full order to an alternative carrier", incremental_cost_usd: 80, projected_customer_delay_hours: 3, late_units: 20, orders: [], allocations: [], source_version: 1 },
  { id: "SHIP-421:r:split-express:v1", kind: "split-express", label: "Fulfill local stock and send the rest express", incremental_cost_usd: 120, projected_customer_delay_hours: 0, late_units: 0,
    orders: [{ priority: "critical", delay_hours: 0, customer: "store" }], allocations: [], source_version: 1 },
];
const investigated = () => ({ source_version: 1, plans, approvals: [], executions: [], bookings: [], preference: null, operator_preferences: null,
  state: { incident_id: "SHIP-421", shipment: { units_on_delayed_route: 20 }, inventory: { arequipa: {} } },
  events: [{ name: "agent_investigation_completed", data: { source_version: 1, answer: "Recommended plan: SHIP-421:r:split-express:v1" } }] });

function harness({ snapshot = investigated(), responses = {}, auth = { enabled: false }, session = null, purchaseState = {} } = {}) {
  const store = createStore({ busy: false, incidentId: "SHIP-421", inbox: [{ incident_id: "SHIP-421", title: "Laptop shipment delayed in transit" }, { incident_id: "SHIP-433", title: "Carrier outage" }],
    snapshot, conversation: [], conversations: {}, selections: {}, selectedPlanId: null, pendingApproval: null, awaitingExecute: false,
    briefingPick: null, memoryIncident: null, forgetting: false, auth, session });
  const said = [];
  const calls = [];
  const events = [];
  const request = async (path, method = "GET", body) => {
    calls.push({ path, method, body });
    const handler = responses[path];
    if (!handler) throw Object.assign(new Error(`unexpected ${path}`), { status: 500 });
    return typeof handler === "function" ? handler(body) : handler;
  };
  const purchase = {
    started: [], confirmed: [], stored: () => purchaseState.stored || null, forget: () => { events.push("purchase.forget"); purchaseState.stored = null; },
    take: () => { const value = purchaseState.pending || null; purchaseState.pending = null; return value; },
    start: async (text) => { purchase.started.push(text); }, confirm: async (p) => { purchase.confirmed.push(p); }, resume: async () => { events.push("purchase.resume"); },
  };
  const commands = createCommands({
    store, intent, request, purchase,
    selectors: { ...selectors, planFromUtterance: (text) => selectors.planFromUtterance(text, store.state.snapshot, intent) },
    badges: { ...badges, noteCheck: (run) => { if (badges.checkNote(run)) events.push("noteCheck"); }, noteFallback: (run) => { if (badges.fallbackNote(run)) events.push("noteFallback"); } },
    preferences: { describe: (prefs) => `described ${prefs.max_cost_usd}`, effect: () => "effect." },
    say: (role, text, meta, spoken, check) => said.push({ role, text, meta, spoken, check }), act: async (work) => work(),
    device: (method) => events.push(`device:${method}`), stopSpeaking: () => events.push("stop"),
    selectIncident: async (id) => { events.push(`select:${id}`); store.set({ incidentId: id }); },
    hideMcpApp: () => events.push("hideMcpApp"), showMcpApp: async () => events.push("showMcpApp"), showMcpAppNote: (text) => events.push(`note:${text}`),
    onInbox: () => events.push("inbox"), approvePlan: async (plan) => { events.push(`approve:${plan.kind}`); store.state.snapshot.approvals.push({ plan_id: plan.id, source_version: plan.source_version }); },
    executeApproved: async () => { events.push("execute"); store.state.snapshot.executions.push({ plan_id: plans[2].id, source_version: 1, accounted_units: 20, incremental_cost_usd: 120, notifications: [1, 2, 3], projected_customer_delay_hours: 0, fulfillments: [] }); },
    savePreferences: async (update) => { events.push(`save:${JSON.stringify(update)}`); store.state.snapshot.operator_preferences = { max_cost_usd: update.max_cost_usd }; },
    linkAccount: async () => events.push("link"), signOut: () => { events.push("signOut"); store.set({ session: null }); },
    onSurface: (name) => events.push(`surface:${name}`),
    investigate: (path, body) => { events.push(`investigate:${path}`); return request(path, "POST", body); },
  });
  const last = () => said.at(-1);
  return { commands, store, said, calls, events, purchase, last };
}

test("help and start over answer without the model and start over clears what was pending", async () => {
  const h = harness();
  await h.commands.handle("what can you do?");
  assert.equal(h.last().text, CAPABILITIES_TEXT);
  assert.equal(h.last().spoken, CAPABILITIES_SPOKEN);
  h.store.set({ pendingApproval: { planId: "x" }, awaitingExecute: true, selectedPlanId: "x" });
  await h.commands.handle("start over");
  assert.match(h.last().text, /Okay, starting over\. Nothing was changed or approved/);
  assert.equal(h.store.state.pendingApproval, null);
  assert.equal(h.store.state.awaitingExecute, false);
  assert.equal(h.store.state.selectedPlanId, null);
  assert.ok(h.events.includes("purchase.forget") && h.events.includes("hideMcpApp"));
  assert.equal(h.calls.length, 0);
  assert.equal(h.said.filter((turn) => turn.role === "user").length, 2);
});

test("start over says what stays in place once a plan is approved or executed, and the result can be reopened", async () => {
  const approval = { plan_id: "SHIP-421:r:split-express:v1", source_version: 1, is_current: true };
  const approved = harness({ snapshot: { ...investigated(), approvals: [approval] } });
  await approved.commands.handle("start over");
  assert.equal(approved.last().text, "Okay, starting over. I cleared our conversation; your approval of “Fulfill local stock and send the rest express” still stands. "
    + "Ask about your queue, or about an incident.");
  assert.equal(approved.last().spoken, "Okay, starting over. Your approval still stands.");
  await approved.commands.handle("show the result");
  assert.equal(approved.last().text, "Nothing has been executed for SHIP-421 yet, so there's no result to show.");
  const executed = harness({ snapshot: { ...investigated(), approvals: [approval], executions: [{ plan_id: approval.plan_id, source_version: 1 }],
    bookings: [{ plan_id: approval.plan_id, number: "LGO-7KQ2MD" }] } });
  await executed.commands.handle("start over");
  assert.match(executed.last().text, /“Fulfill local stock and send the rest express” stays executed, and booking LGO-7KQ2MD stays paid \(simulated\)\./);
  assert.ok(!executed.last().text.includes("Nothing was changed"));
  await executed.commands.handle("show the result");
  assert.equal(executed.last().text, "Here's the result for SHIP-421.");
  assert.ok(executed.events.includes("surface:result"));
  assert.equal(executed.calls.length, 0);
});

test("an approval is read back and only an explicit yes approves; execute refuses another plan", async () => {
  const h = harness();
  await h.commands.handle("approve the recommended plan");
  assert.equal(h.last().text, "Approve “Fulfill local stock and send the rest express” for $120 extra, no delay? Say “yes” to approve it, or ask me anything else.");
  assert.deepEqual(h.store.state.pendingApproval, { planId: plans[2].id, sourceVersion: 1 });
  await h.commands.handle("yes");
  assert.ok(h.events.includes("approve:split-express"));
  assert.equal(h.last().text, "Approved “Fulfill local stock and send the rest express” on the current data. Nothing has run yet: say “execute it” when you're ready.");
  assert.equal(h.store.state.awaitingExecute, true);
  await h.commands.handle("execute the wait plan");
  assert.match(h.last().text, /The approved plan is “Fulfill local stock and send the rest express”, so nothing was executed\. Approve “Keep the delayed shipment” first/);
  assert.ok(!h.events.includes("execute"));
  await h.commands.handle("execute it");
  assert.ok(h.events.includes("execute"));
  assert.match(h.last().text, /^The plan was executed\. Verified: 20 units accounted for · \$120 extra · 3 simulated notifications/);
  await h.commands.handle("execute it");
  assert.match(h.last().text, /SHIP-421 was already executed/);
});

test("yes with nothing pending, a stale read-back, and a missing or unknown plan", async () => {
  const h = harness();
  await h.commands.handle("yes");
  assert.match(h.last().text, /Nothing is waiting for a “yes” right now/);
  await h.commands.handle("approve the $999 plan");
  assert.match(h.last().text, /That plan isn't available for the current data\. The options are “Keep the delayed shipment” \(\$0\)/);
  await h.commands.handle("approve the split plan");
  h.store.state.snapshot.plans = [];
  await h.commands.handle("yes");
  assert.match(h.last().text, /The data changed after I read that plan back, so nothing was approved/);
  const empty = harness({ snapshot: { ...investigated(), plans: [] } });
  await empty.commands.handle("approve it");
  assert.match(empty.last().text, /There are no plans for the current data yet/);
});

test("a question investigates or follows up, shows the card for a fresh investigation and notes the check", async () => {
  const responses = {
    "/incidents/SHIP-421/agent/investigate": { answer: "A", spoken: "a", tool_trace: [1, 2], mode: "replay", usage: {}, evaluations: [{ issues: ["$99 is not in the data"] }], grounded: false },
    "/incidents/SHIP-421/agent/ask": { answer: "B", spoken: "b", tool_trace: [], mode: "replay", usage: {}, fallback: "daily_budget" },
  };
  const fresh = harness({ snapshot: { ...investigated(), events: [] }, responses });
  await fresh.commands.handle("What's happening with SHIP-421?");
  assert.equal(fresh.calls[0].path, "/incidents/SHIP-421/agent/investigate");
  assert.ok(fresh.events.includes("investigate:/incidents/SHIP-421/agent/investigate"), "an investigation goes through the streaming hook");
  assert.equal(fresh.last().meta, "investigation · 2 MCP calls · replay mode · 0 tokens");
  assert.deepEqual(fresh.last().check, { passed: false, text: "Did not pass the data check: $99 is not in the data" });
  assert.ok(fresh.events.includes("showMcpApp") && fresh.events.includes("noteCheck") && fresh.events.includes("device:trace"));
  const bare = harness({ responses });
  await bare.commands.handle("investigate");
  assert.equal(bare.calls[0].path, "/incidents/SHIP-421/agent/investigate");
  const follow = harness({ responses });
  await follow.commands.handle("Why not the cheaper one?");
  assert.equal(follow.calls[0].path, "/incidents/SHIP-421/agent/ask");
  assert.ok(!follow.events.some((event) => event.startsWith("investigate:")), "a follow-up does not stream");
  assert.deepEqual(follow.calls[0].body.history, []);
  assert.equal(follow.last().meta, "follow-up · 0 MCP calls · replay mode · daily live budget used · 0 tokens");
  assert.ok(follow.events.includes("noteFallback") && !follow.events.includes("showMcpApp"));
  const executed = harness({ snapshot: { ...investigated(), events: [], executions: [{ plan_id: "x", source_version: 1 }] } });
  await executed.commands.handle("why?");
  assert.match(executed.last().text, /already executed without an investigation to refer to/);
  const failing = harness({ responses: { "/incidents/SHIP-421/agent/ask": () => { throw new Error("I couldn't reach the planning service just now."); } } });
  await failing.commands.handle("why?");
  assert.equal(failing.last().text, "I couldn't do that: I couldn't reach the planning service just now.");
});

test("a mentioned incident is opened first, a briefing reads the inbox and remember saves preferences", async () => {
  const h = harness({ responses: {
    "/agent/briefing": { answer: "Start with: SHIP-433", spoken: "s", tool_trace: [1], mode: "replay", usage: {}, start_with: "SHIP-433" },
    "/operator/preferences": {},
  } });
  await h.commands.handle("open SHIP-433");
  assert.deepEqual(h.events.slice(0, 2), ["stop", "select:SHIP-433"]);
  assert.match(h.last().text, /^Opened SHIP-433: Carrier outage/);
  await h.commands.handle("any delays today?");
  assert.equal(h.store.state.briefingPick, "SHIP-433");
  assert.ok(h.events.includes("inbox"));
  assert.match(h.last().meta, /^briefing · 1 MCP call · /);
  await h.commands.handle("remember my spend cap is $250");
  assert.ok(h.events.includes('save:{"max_cost_usd":250}'));
  assert.equal(h.last().text, "Saved for every incident: described 250. effect. Preferences never approve anything; you still approve the plan.");
  await h.commands.handle("forget my preferences");
  assert.deepEqual(h.calls.at(-1), { path: "/operator/preferences", method: "DELETE", body: undefined });
  assert.match(h.last().text, /I forgot your saved preferences/);
});

test("book, yes, no and resume go through the purchase module", async () => {
  const state = {};
  const h = harness({ purchaseState: state, responses: { "/demo/reset": {} } });
  await h.commands.handle("book the express plan");
  assert.deepEqual(h.purchase.started, ["book the express plan"]);
  state.pending = { key: "k" };
  await h.commands.handle("yes");
  assert.deepEqual(h.purchase.confirmed, [{ key: "k" }]);
  state.stored = { key: "k" };
  await h.commands.handle("no");
  assert.equal(h.last().text, "Okay, nothing was booked or charged.");
  await h.commands.handle("no");
  assert.equal(h.last().text, "Okay. Ask me anything else about the queue or this incident.");
  await h.commands.handle("resume");
  assert.ok(h.events.includes("purchase.resume"));
  await h.commands.handle("reset");
  assert.deepEqual(h.calls.at(-1), { path: "/demo/reset", method: "POST", body: { incident_id: "SHIP-421" } });
  assert.match(h.last().text, /SHIP-421 is back to its original state/);
});

test("memory and account commands", async () => {
  const guest = harness({ auth: { enabled: true } });
  await guest.commands.handle("forget me");
  assert.match(guest.last().text, /I don't remember guests/);
  await guest.commands.handle("sign out");
  assert.equal(guest.last().text, "You're not signed in.");
  await guest.commands.handle("link my account");
  assert.ok(guest.events.includes("link"));
  const user = harness({ auth: { enabled: true }, session: { username: "judge" }, responses: { "/memory": { forgotten: 3 } } });
  await user.commands.handle("forget me");
  assert.equal(user.last().text, "Done. I forgot our earlier conversations (3 items). Your saved preferences stay until you say “forget my preferences”.");
  assert.equal(user.store.state.forgetting, false);
  await user.commands.handle("link my account");
  assert.equal(user.last().text, "You're already signed in as judge.");
  await user.commands.handle("sign out");
  assert.ok(user.events.includes("signOut"));
  await user.commands.handle("pick up where we left off");
  assert.match(user.last().text, /I don't have an earlier conversation to pick up/);
  user.store.set({ memoryIncident: "SHIP-433" });
  await user.commands.handle("where were we");
  assert.ok(user.events.includes("select:SHIP-433"));
  assert.equal(user.last().text, "Back on SHIP-433. Ask what's happening, or say “approve the recommended plan”.");
  assert.equal(user.store.state.conversation.at(-1).text, "where were we");
});

test("a line with no words to act on asks again instead of calling the agent", async () => {
  const h = harness();
  await h.commands.handle("asdf qwer");
  assert.equal(h.last().text, "I didn't catch that. Ask “any delays today?”, or ask what's happening with SHIP-421.");
  assert.equal(h.last().meta, "not understood");
  await h.commands.handle("12345");
  await h.commands.handle("again?");
  assert.equal(h.last().meta, "not understood");
  assert.equal(h.calls.length, 0);
  assert.equal(h.store.state.pendingApproval, null);
});

test("the plans and the incident can be shown again by voice, text or a chip", async () => {
  const h = harness();
  await h.commands.handle("show the incident");
  assert.equal(h.last().text, "Here's SHIP-421: Laptop shipment delayed in transit. Say “show the plans” or “approve the recommended plan”.");
  assert.equal(h.events.at(-1), "surface:incident");
  await h.commands.handle("Show the plans");
  assert.equal(h.last().text, "Here are the 3 plans for SHIP-421. Only you approve.");
  assert.equal(h.events.at(-1), "surface:plans");
  await h.commands.handle("open SHIP-421");
  assert.match(h.last().text, /^Opened SHIP-421: Laptop shipment delayed in transit\. Say “show the plans”/);
  assert.equal(h.events.at(-1), "surface:incident");
  const empty = harness({ snapshot: { ...investigated(), plans: [] } });
  await empty.commands.handle("back to the plans");
  assert.equal(empty.last().text, "There are no plans for the current data yet. Ask me what's happening first.");
  assert.ok(!empty.events.some((event) => event.startsWith("surface:")));
  assert.equal(h.calls.length + empty.calls.length, 0);
});

test("approval read-backs name the cost, the delay and a critical order left late", () => {
  assert.equal(approvalReadback(plans[1]), "Approve “Move the full order to an alternative carrier” for $80 extra, 3 hours of delay?");
  assert.equal(approvalReadback({ ...plans[1], orders: [{ priority: "critical", delay_hours: 3, customer: "the hospital" }] }),
    "Approve “Move the full order to an alternative carrier” for $80 extra, 3 hours of delay, and it leaves the critical order for the hospital late?");
});

test("execute before any approval says what to do next and calls nothing", async () => {
  const h = harness();
  await h.commands.handle("execute it");
  assert.equal(h.last().text, "Nothing is approved for SHIP-421 yet, so nothing ran. Say “approve the recommended plan” first, and I'll read it back.");
  const fresh = harness({ snapshot: { ...investigated(), plans: [] } });
  await fresh.commands.handle("execute it");
  assert.equal(fresh.last().text, "Nothing is approved for SHIP-421 yet, so nothing ran. Ask me what's happening with SHIP-421 first, then approve a plan.");
  assert.equal(h.calls.length + fresh.calls.length, 0);
});

test("a standing approval blocks a second one, and withdrawing it is read back, then resets the incident", async () => {
  const approval = { plan_id: "SHIP-421:r:split-express:v1", source_version: 1, is_current: true };
  const h = harness({ snapshot: { ...investigated(), approvals: [approval] }, responses: { "/demo/reset": {}, "/incidents": { incidents: [] } } });
  await h.commands.handle("approve the wait plan");
  assert.equal(h.last().text, "“Fulfill local stock and send the rest express” is already approved for this data, so I can't approve another plan. "
    + "Say “withdraw the approval” first if you want to choose again.");
  await h.commands.handle("approve the recommended plan");
  assert.match(h.last().text, /is already approved\. Say “execute it”/);
  assert.equal(h.calls.length, 0);
  await h.commands.handle("withdraw the approval");
  assert.match(h.last().text, /^Withdraw the approval of “Fulfill local stock and send the rest express”\? .* resets SHIP-421 to its original data/);
  assert.ok(h.events.includes("surface:confirm"));
  await h.commands.handle("no");
  assert.equal(h.last().text, "Okay, the approval of “Fulfill local stock and send the rest express” stays.");
  assert.equal(h.calls.length, 0);
  await h.commands.handle("cancel the approval");
  await h.commands.handle("yes");
  assert.deepEqual(h.calls.map((call) => [call.path, call.body?.incident_id]), [["/demo/reset", "SHIP-421"]]);
  assert.match(h.last().text, /^Done\. The approval of “Fulfill local stock and send the rest express” is withdrawn/);
  const booked = harness({ snapshot: { ...investigated(), approvals: [approval], bookings: [{ plan_id: approval.plan_id }] } });
  await booked.commands.handle("withdraw the approval");
  assert.equal(booked.last().text, "“Fulfill local stock and send the rest express” is already booked and paid, so its approval stays.");
  const none = harness();
  await none.commands.handle("undo the approval");
  assert.equal(none.last().text, "Nothing is approved for SHIP-421, so there's nothing to withdraw.");
});

test("going home is a closed command that keeps the conversation and calls nothing", async () => {
  const h = harness();
  await h.commands.handle("approve the recommended plan");
  for (const line of ["home", "go back", "back to the queue", "show me the inbox"]) {
    await h.commands.handle(line);
    assert.equal(h.last().text, "Here's your queue: 2 open incidents.", line);
  }
  assert.ok(h.events.filter((event) => event === "surface:home").length === 4);
  assert.ok(!h.events.includes("hideMcpApp"), "going home clears nothing");
  assert.equal(h.calls.length, 0);
});
