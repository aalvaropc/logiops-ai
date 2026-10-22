import { test } from "node:test";
import assert from "node:assert/strict";
import { moduleUrl } from "./helpers.mjs";

const { seconds, sessionFigures, incidentTimes } = await import(moduleUrl("app/metrics.js"));

test("durations read as seconds, minutes or hours, and the session strip names each figure", () => {
  assert.equal(seconds(null), null);
  assert.equal(seconds(12.4), "12 s");
  assert.equal(seconds(75), "1 min 15 s");
  assert.equal(seconds(3599.6), "1 h 0 min");
  assert.equal(seconds(82513.7), "22 h 55 min");
  const totals = { incidents: 4, investigated: 2, decided: 2, executed: 1, extra_cost_usd: 120, booked_usd: 147.5, late_units: 0, median_time_to_decision_s: 42.6 };
  assert.deepEqual(sessionFigures(totals), [
    ["1 of 4", "incidents executed"], ["2", "plans approved"], ["$120", "extra cost committed"], ["$147.50", "booked and paid"],
    ["0", "units late after execution"], ["43 s", "median time to decision"],
  ]);
  assert.deepEqual(sessionFigures({ ...totals, median_time_to_decision_s: null })[5], ["—", "median time to decision"]);
  assert.deepEqual(sessionFigures({ ...totals, decided: 1, incidents: 1, executed: 1 }).slice(0, 2), [["1 of 1", "incident executed"], ["1", "plan approved"]]);
  assert.deepEqual(sessionFigures({ ...totals, decided: 0, executed: 0, booked_usd: 0 }), []);
  assert.deepEqual(sessionFigures({ ...totals, decided: 0, executed: 0, booked_usd: 0 }, { always: true })[1], ["0", "plans approved"]);
  assert.deepEqual(incidentTimes({ time_to_decision_s: 10, time_to_execution_s: null }), [["Decided in", "10 s"]]);
  assert.deepEqual(incidentTimes(undefined), []);
});
