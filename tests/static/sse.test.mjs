import { test } from "node:test";
import assert from "node:assert/strict";
import { moduleUrl } from "./helpers.mjs";

const { parseSse } = await import(moduleUrl("app/sse.js"));

test("server-sent events are read whole and a partial block waits for the rest", () => {
  const first = parseSse('event: step\ndata: {"tool":"get_shipment"}\n\nevent: ping\ndata: {}\n\nevent: do');
  assert.deepEqual(first.events, [["step", { tool: "get_shipment" }], ["ping", {}]]);
  assert.equal(first.rest, "event: do");
  const second = parseSse(`${first.rest}ne\r\ndata: {"answer":"ok"}\r\n\r\n`);
  assert.deepEqual(second.events, [["done", { answer: "ok" }]]);
  assert.equal(second.rest, "");
  assert.deepEqual(parseSse(": comment\n\n").events, []);
});
