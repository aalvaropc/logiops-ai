import { test } from "node:test";
import assert from "node:assert/strict";
import { moduleUrl } from "./helpers.mjs";

const { showMessage, parkedPurchaseLine, openHtml, loadAuthInto, createFocusKeeper } = await import(moduleUrl("app/page.js"));

function box() {
  const attributes = {};
  return { textContent: "", className: "", attributes, setAttribute(name, value) { attributes[name] = value; } };
}

function fakeDocument() {
  const doc = { body: { isConnected: true, closest: () => null } };
  const node = (name, { disabled = false, hidden = false, connected = true, say } = {}) => ({
    name, disabled, isConnected: connected, dataset: say === undefined ? {} : { say },
    closest: () => (hidden ? {} : null), focus() { doc.activeElement = this; },
  });
  doc.activeElement = doc.body;
  return { doc, node };
}

test("a message is a polite status when it is good news and an assertive alert otherwise", () => {
  const shown = box();
  showMessage(shown, "Connected.", true);
  assert.deepEqual([shown.textContent, shown.className, shown.attributes.role, shown.attributes["aria-live"]], ["Connected.", "message visible success", "status", "polite"]);
  showMessage(shown, "Something failed");
  assert.deepEqual([shown.className, shown.attributes.role, shown.attributes["aria-live"]], ["message visible", "alert", "assertive"]);
  showMessage(shown, "");
  assert.deepEqual([shown.className, shown.attributes.role], ["message", "status"]);
});

test("a parked purchase is read back with its price and how to resume or drop it", () => {
  const line = parkedPurchaseLine({ incidentId: "SHIP-421", quote: { plan_label: "Split", total_usd: 147.5 } }, (value) => `$${value.toFixed(2)}`);
  assert.equal(line, "A booking is waiting for “Split” on SHIP-421 ($147.50). Say “resume” to hear the price again, or “no” to drop it. Nothing was charged.");
});

test("a receipt opens in a new tab and its blob address is released later", () => {
  const calls = [];
  openHtml("<p>receipt</p>", {
    win: { open: (url, target) => calls.push(["open", url, target]) },
    urls: { createObjectURL: () => "blob:1", revokeObjectURL: (url) => calls.push(["revoke", url]) },
    later: (work, ms) => { calls.push(["later", ms]); work(); },
  });
  assert.deepEqual(calls, [["open", "blob:1", "_blank"], ["later", 60000], ["revoke", "blob:1"]]);
});

test("the sign-in settings are loaded into the page, and an unreadable answer is an error to retry", async () => {
  const state = { auth: { enabled: false } };
  const kept = [];
  let rendered = 0;
  const load = (answer) => loadAuthInto({ api: { loadAuth: async () => answer }, state, keepSession: (value) => kept.push(value), renderAccount: () => { rendered += 1; } });
  await assert.rejects(load({ enabled: false, unavailable: true }), /could not be read/);
  await load({ enabled: true, client_id: "c" });
  assert.deepEqual([state.auth.client_id, kept, rendered], ["c", [], 1]);
  await load({ enabled: false });
  assert.deepEqual([kept, rendered], [[null], 2]);
});

test("the focus comes back after busy work, or moves on when its control is gone", () => {
  const { doc, node } = fakeDocument();
  const approve = node("approve");
  const execute = node("execute");
  const keeper = createFocusKeeper({ doc, fallback: (before) => (before === approve ? execute : null) });
  keeper.remember(approve);
  keeper.restore();
  assert.equal(doc.activeElement, approve, "the same control when it is still usable");
  doc.activeElement = doc.body;
  approve.disabled = true;
  keeper.remember(approve);
  keeper.restore();
  assert.equal(doc.activeElement, execute, "the next one when it is disabled");
  const elsewhere = node("elsewhere");
  doc.activeElement = elsewhere;
  keeper.remember(execute);
  keeper.restore();
  assert.equal(doc.activeElement, elsewhere, "a focus the page moved on purpose is left alone");
  doc.activeElement = approve;
  keeper.handTo(node("account"));
  keeper.restore();
  assert.equal(doc.activeElement.name, "account", "a disabled focused control counts as lost, and a hand-off wins");
  doc.activeElement = doc.body;
  keeper.remember(node("hidden", { hidden: true }));
  keeper.restore();
  assert.equal(doc.activeElement, doc.body, "nothing hidden is focused");
});
