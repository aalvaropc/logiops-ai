import { test } from "node:test";
import assert from "node:assert/strict";
import { moduleUrl, memoryStorage } from "./helpers.mjs";

const { createPurchase, purchaseReadback, dollars, spelled, bookingRows, PURCHASE_KEY } = await import(moduleUrl("app/purchase.js"));
const { createStorage } = await import(moduleUrl("app/api.js"));
const selectors = await import(moduleUrl("app/selectors.js"));

const quote = {
  quote_id: "Q-1", plan_label: "Fulfill local stock and send the rest express", base_usd: 120, service_fee_usd: 5, igv_usd: 22.5, total_usd: 147.5,
  payment_method: "Corporate card ending 4242 (simulated)", expires_at: new Date(Date.now() + 600000).toISOString(), approved: false,
};
const plans = [
  { id: "p-wait", kind: "wait", label: "Keep the delayed shipment", incremental_cost_usd: 0, projected_customer_delay_hours: 12, orders: [], allocations: [], source_version: 1 },
  { id: "p-express", kind: "split-express", label: quote.plan_label, incremental_cost_usd: 120, projected_customer_delay_hours: 0,
    orders: [{ priority: "critical", delay_hours: 0, customer: "hospital" }], allocations: [], source_version: 1 },
];

function setup({ snapshot: initial, responses = {}, approved = false, now } = {}) {
  const said = [];
  const bookings = [];
  const calls = [];
  const storage = createStorage(memoryStorage());
  const state = { snapshot: initial ?? { source_version: 1, plans, approvals: [], executions: [], bookings: [], preference: null, events: [] } };
  const request = async (path, method, body) => {
    calls.push({ path, method, body });
    const handler = responses[path] ?? responses["*"];
    if (!handler) throw Object.assign(new Error(`unexpected ${path}`), { status: 500 });
    return typeof handler === "function" ? handler(body) : handler;
  };
  const purchase = createPurchase({
    storage, request, crypto: { randomUUID: () => "1234" }, now: now ?? (() => Date.now()),
    api: { token: () => "", fetch: async () => ({ ok: true, text: async () => "<html>receipt</html>" }), explain: (status) => `explained ${status}` },
    selectors: { ...selectors, planFromUtterance: (text) => selectors.planFromUtterance(text, state.snapshot, { planSelector: () => ({}), recommendedPlanId: () => null }) },
    snapshot: () => state.snapshot, incidentId: () => "SHIP-421",
    say: (role, text, meta, spoken) => said.push({ role, text, meta, spoken }), act: async (work) => work(),
    approvePlan: async (plan) => { state.snapshot.approvals.push({ plan_id: plan.id, source_version: plan.source_version }); },
    onBooking: (booking) => bookings.push(booking),
  });
  if (approved) state.snapshot.approvals.push({ plan_id: "p-express", source_version: 1 });
  return { purchase, said, bookings, calls, storage, state };
}

test("the read-back lists the breakdown and asks for approval only when the plan needs it", () => {
  const unapproved = purchaseReadback({ approve: true, quote }, plans[1]);
  assert.equal(unapproved.text, "To approve “Fulfill local stock and send the rest express” (no delay) and book it: carriers and services $120.00, service fee $5.00, "
    + "IGV 18% $22.50, total $147.50, charged to the corporate card ending 4242. Say “yes” to approve and pay, or “no”.");
  const late = purchaseReadback({ approve: true, quote }, { ...plans[1], projected_customer_delay_hours: 8, orders: [{ priority: "critical", delay_hours: 8, customer: "the hospital" }] });
  assert.match(late.text, /\(8 hours of delay\) and book it: .* It leaves the critical order for the hospital late\. Say “yes”/);
  assert.equal(purchaseReadback({ approve: false, quote }, plans[1]).text, "To book “Fulfill local stock and send the rest express”: carriers and services $120.00, service fee $5.00, "
    + "IGV 18% $22.50, total $147.50, charged to the corporate card ending 4242. Say “yes” to pay, or “no”.");
  assert.equal(dollars(1234.5), "$1,234.50");
  assert.equal(spelled("LGO-7K2M9Q"), "L G O 7 K 2 M 9 Q");
  assert.deepEqual(bookingRows({ lines: [{ service: "Express", units: 8, cost_usd: 120 }, { service: "Stock", units: 12 }], base_usd: 120, service_fee_usd: 5, igv_usd: 22.5, total_usd: 147.5 }),
    [["Express, 8 units", "$120.00"], ["Stock, 12 units", "included"], ["Carriers and services", "$120.00"], ["Service fee", "$5.00"], ["IGV 18%", "$22.50"], ["Total", "$147.50"]]);
});

test("book it quotes the named plan, keeps the purchase and reads it back; yes approves and pays once", async () => {
  const booking = { number: "LGO-ABC234", total_usd: 147.5, confirmation: "Booked “Fulfill…” for SHIP-421: $147.50 charged." };
  const { purchase, said, bookings, calls, storage } = setup({ responses: { "/incidents/SHIP-421/bookings/quote": quote, "/quotes/Q-1/confirm": booking } });
  const started = await purchase.start("book the split plan");
  assert.equal(started.planId, "p-express");
  assert.equal(started.approve, true);
  assert.equal(started.key, "buy-1234");
  assert.deepEqual(calls[0], { path: "/incidents/SHIP-421/bookings/quote", method: "POST", body: { plan_id: "p-express" } });
  assert.match(said[0].text, /Say “yes” to approve and pay, or “no”\./);
  assert.equal(said[0].meta, "price read-back · nothing charged yet");
  assert.equal(JSON.parse(storage.get(PURCHASE_KEY)).quote.quote_id, "Q-1");
  const pending = purchase.take();
  assert.equal(purchase.pending(), null);
  const paid = await purchase.confirm(pending);
  assert.equal(paid.number, "LGO-ABC234");
  assert.deepEqual(calls[1], { path: "/quotes/Q-1/confirm", method: "POST", body: { confirmed_total_usd: 147.5, idempotency_key: "buy-1234" } });
  assert.equal(bookings[0], booking);
  assert.equal(storage.get(PURCHASE_KEY), null);
  assert.equal(said[1].text, "Approved. Booked “Fulfill…” for SHIP-421: $147.50 charged. The receipt is in the execute panel.");
  assert.equal(said[1].spoken, "Approved, and booked. $147.50 charged. Your confirmation number is L G O A B C 2 3 4.");
});

test("refusals explain themselves: no plans, a conflicting name, already booked, nothing to pay", async () => {
  const empty = setup({ snapshot: { source_version: 1, plans: [], approvals: [], executions: [], bookings: [] } });
  assert.equal(await empty.purchase.start("book it"), null);
  assert.match(empty.said[0].text, /no plans for the current data/);
  const approved = setup({ approved: true });
  assert.equal(await approved.purchase.start("book the wait plan"), null);
  assert.match(approved.said[0].text, /The approved plan is “Fulfill local stock and send the rest express”, so that's the only one I can book/);
  const booked = setup({ snapshot: { source_version: 1, plans, approvals: [], executions: [], bookings: [{ plan_id: "p-express", number: "LGO-OLD111", total_usd: 147.5 }] } });
  assert.equal(await booked.purchase.start("book the split plan"), null);
  assert.match(booked.said[0].text, /already booked as LGO-OLD111: \$147\.50 was charged once/);
  assert.equal(booked.bookings[0].number, "LGO-OLD111");
  const free = setup();
  assert.equal(await free.purchase.start("book the wait plan"), null);
  assert.match(free.said[0].text, /uses no paid carrier or service/);
});

test("a 5xx keeps the purchase for a retry with the same key, a 4xx drops it, an expired quote is refused", async () => {
  const flaky = setup({ responses: { "/incidents/SHIP-421/bookings/quote": { ...quote, approved: true }, "/quotes/Q-1/confirm": () => { throw Object.assign(new Error("down"), { status: 502 }); } } });
  await flaky.purchase.start("book it");
  assert.equal(await flaky.purchase.confirm(flaky.purchase.take()), null);
  assert.match(flaky.said[1].text, /didn't go through: down Say “yes” to try again; it never charges twice\./);
  assert.equal(flaky.storage.getJson(PURCHASE_KEY).key, "buy-1234", "the key survives for the retry");
  const refused = setup({ responses: { "/incidents/SHIP-421/bookings/quote": { ...quote, approved: true }, "/quotes/Q-1/confirm": () => { throw Object.assign(new Error("Nothing was charged."), { status: 409 }); } } });
  await refused.purchase.start("book it");
  assert.equal(await refused.purchase.confirm(refused.purchase.take()), null);
  assert.equal(refused.storage.get(PURCHASE_KEY), null);
  const stale = setup({ responses: { "/incidents/SHIP-421/bookings/quote": { ...quote, expires_at: new Date(Date.now() - 1000).toISOString() } } });
  await stale.purchase.start("book it");
  assert.equal(await stale.purchase.confirm(stale.purchase.take()), null);
  assert.match(stale.said[1].text, /That price expired, so nothing was charged/);
});

test("resume reads a parked purchase back, or says none is waiting", async () => {
  const { purchase, said, storage } = setup();
  assert.equal(await purchase.resume(async () => {}), null);
  assert.match(said[0].text, /There's no booking waiting/);
  storage.set(PURCHASE_KEY, JSON.stringify({ incidentId: "SHIP-421", planId: "p-express", sourceVersion: 1, approve: false, quote, key: "buy-old" }));
  const parked = await purchase.resume(async () => {});
  assert.equal(parked.key, "buy-old");
  assert.match(said[1].text, /^To book “Fulfill local stock/);
  assert.equal(purchase.pending().key, "buy-old");
  assert.equal(await purchase.openReceipt("LGO-ABC234"), "<html>receipt</html>");
});
