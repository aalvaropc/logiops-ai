import { test } from "node:test";
import assert from "node:assert/strict";
import { moduleUrl } from "./helpers.mjs";

const { createStore } = await import(moduleUrl("app/store.js"));

test("set merges a patch or a function result and notifies subscribers of changed slices", () => {
  const store = createStore({ busy: false, incidentId: "SHIP-421", alerts: [] });
  const seen = [];
  const unsubscribe = store.subscribe((next, before) => seen.push([before, next]), (state) => state.incidentId);
  store.set({ busy: true });
  assert.equal(store.get().busy, true);
  assert.deepEqual(seen, [], "an untouched slice does not notify");
  store.set((state) => ({ incidentId: `${state.incidentId}-x` }));
  assert.deepEqual(seen, [["SHIP-421", "SHIP-421-x"]]);
  unsubscribe();
  store.set({ incidentId: "SHIP-433" });
  assert.equal(seen.length, 1);
  assert.equal(store.state, store.get(), "the live object stays the same instance");
});

test("whole-state subscribers see every change and bad patches are ignored", () => {
  const store = createStore({ a: 1 });
  let calls = 0;
  store.subscribe(() => { calls += 1; });
  store.set(null);
  store.set("nope");
  assert.equal(calls, 0);
  store.set({ b: 2 });
  assert.equal(calls, 1);
  assert.deepEqual(store.get(), { a: 1, b: 2 });
});
