import { test } from "node:test";
import assert from "node:assert/strict";
import { moduleUrl } from "./helpers.mjs";

const { createAlerts, bellText } = await import(moduleUrl("app/alerts.js"));

const alertFor = (incident, id = `${incident}-v2`) => ({ id, incident_id: incident, message: `Heads up on ${incident}`, spoken: "Heads up", new_plan: { plan_id: `${incident}-plan` } });

test("the bell counts the alerts of other incidents", () => {
  assert.equal(bellText([], "SHIP-421"), null);
  assert.equal(bellText([alertFor("SHIP-421")], "SHIP-421"), null);
  assert.deepEqual(bellText([alertFor("SHIP-452"), alertFor("SHIP-460")], "SHIP-421"),
    { count: 2, incidentId: "SHIP-452", text: "2 alerts · SHIP-452", label: "2 proactive alerts; open SHIP-452" });
});

test("a check announces the open incident's alert after dismissing it, and keeps the others", async () => {
  const calls = [];
  const announced = [];
  const shown = [];
  let busy = false;
  const alerts = createAlerts({
    request: async (path, method) => { calls.push(`${method || "GET"} ${path}`); return { alerts: [alertFor("SHIP-421"), alertFor("SHIP-452")] }; },
    incidentId: () => "SHIP-421", isBusy: () => busy, onAlerts: (list) => shown.push(list.map((item) => item.id)),
    onAnnounce: async (alert) => announced.push(alert.id),
  });
  await alerts.check();
  assert.deepEqual(calls, ["GET /alerts", "POST /alerts/SHIP-421-v2/dismiss"]);
  assert.deepEqual(announced, ["SHIP-421-v2"]);
  assert.deepEqual(shown, [["SHIP-421-v2", "SHIP-452-v2"], ["SHIP-452-v2"]]);
  assert.equal(alerts.elsewhere().id, "SHIP-452-v2");
  busy = true;
  await alerts.check();
  assert.equal(calls.length, 2, "nothing is fetched while the page is busy");
});

test("the alerts can be read through another source, while dismissing stays on the API", async () => {
  const calls = [];
  const alerts = createAlerts({
    request: async (path, method) => { calls.push(`${method || "GET"} ${path}`); return {}; },
    list: async () => { calls.push("tools/call list_alerts"); return { alerts: [alertFor("SHIP-421")] }; },
    incidentId: () => "SHIP-421", onAnnounce: async () => {},
  });
  await alerts.check();
  assert.deepEqual(calls, ["tools/call list_alerts", "POST /alerts/SHIP-421-v2/dismiss"]);
});

test("failures leave the alerts as they were", async () => {
  let fail = true;
  const alerts = createAlerts({
    request: async (path) => { if (fail) throw new Error("502"); return { alerts: [] }; },
    incidentId: () => "SHIP-421", isHidden: () => false, onAnnounce: async () => {},
  });
  assert.deepEqual(await alerts.check(), []);
  assert.equal(await alerts.announce(alertFor("SHIP-452")), false);
  fail = false;
  assert.deepEqual(await alerts.check(), []);
  const hidden = createAlerts({ request: async () => { throw new Error("should not fetch"); }, incidentId: () => "x", isHidden: () => true, onAnnounce: async () => {} });
  assert.deepEqual(await hidden.check(), []);
});

test("overlapping checks read the alerts once and announce each alert once", async () => {
  const calls = [];
  const announced = [];
  let release;
  const opened = new Promise((resolve) => { release = resolve; });
  const alerts = createAlerts({
    request: async (path, method) => { calls.push(`${method || "GET"} ${path}`); return {}; },
    list: async () => { calls.push("list"); await opened; return { alerts: [alertFor("SHIP-421")] }; },
    incidentId: () => "SHIP-421", onAnnounce: async (alert) => announced.push(alert.id),
  });
  const first = alerts.check();
  const second = alerts.check();
  release();
  await Promise.all([first, second]);
  assert.deepEqual(calls, ["list", "POST /alerts/SHIP-421-v2/dismiss"]);
  assert.deepEqual(announced, ["SHIP-421-v2"]);
  assert.equal(await alerts.announce(alertFor("SHIP-421")), false, "an alert already announced is not announced again");
  await alerts.check();
  assert.deepEqual(announced, ["SHIP-421-v2"], "a list that still carries the dismissed alert does not repeat it");
});

