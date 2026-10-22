import { test } from "node:test";
import assert from "node:assert/strict";
import { moduleUrl } from "./helpers.mjs";

const { createStartup } = await import(moduleUrl("app/startup.js"));

function setup({ failures = 0, delays = [10, 20], retryable } = {}) {
  const log = [];
  const pauses = [];
  let remaining = failures;
  const startup = createStartup({
    delays, retryable,
    attempt: async () => {
      log.push("attempt");
      if (remaining > 0) {
        remaining -= 1;
        throw Object.assign(new Error("down"), { status: 503 });
      }
    },
    wait: async (ms) => { pauses.push(ms); },
    onFailure: (error, { retryIn }) => log.push(`failure:${retryIn}`),
    onSuccess: (recovered) => log.push(`success:${recovered}`),
  });
  return { startup, log, pauses, recover: () => { remaining = 0; } };
}

test("a first load that works reports success without a recovery", async () => {
  const { startup, log } = setup();
  assert.equal(await startup.start(), true);
  assert.deepEqual(log, ["attempt", "success:false"]);
});

test("a failed first load is retried after growing pauses and reports the recovery once", async () => {
  const { startup, log, pauses } = setup({ failures: 2 });
  assert.equal(await startup.start(), true);
  assert.deepEqual(pauses, [10, 20]);
  assert.deepEqual(log, ["attempt", "failure:10", "attempt", "failure:20", "attempt", "success:true"]);
});

test("the automatic retries are bounded and the last failure says nobody will retry", async () => {
  const { startup, log, pauses, recover } = setup({ failures: 99 });
  assert.equal(await startup.start(), false);
  assert.deepEqual(pauses, [10, 20]);
  assert.deepEqual(log, ["attempt", "failure:10", "attempt", "failure:20", "attempt", "failure:null"]);
  recover();
  assert.equal(await startup.start(), true);
  assert.deepEqual(log.slice(6), ["attempt", "success:true"]);
});

test("an error that cannot get better by waiting is not retried", async () => {
  const { startup, log, pauses } = setup({ failures: 99, retryable: (error) => error.status !== 503 });
  assert.equal(await startup.start(), false);
  assert.deepEqual(pauses, []);
  assert.deepEqual(log, ["attempt", "failure:null"]);
});

test("a manual retry during a pause supersedes the waiting loop", async () => {
  const log = [];
  const releases = [];
  let healthy = false;
  const startup = createStartup({
    delays: [10],
    attempt: async () => { log.push("attempt"); if (!healthy) throw new Error("down"); },
    wait: () => new Promise((resolve) => releases.push(resolve)),
    onFailure: (error, { retryIn }) => log.push(`failure:${retryIn}`),
    onSuccess: (recovered) => log.push(`success:${recovered}`),
  });
  const waiting = startup.start();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(log, ["attempt", "failure:10"]);
  healthy = true;
  assert.equal(await startup.start(), true);
  releases[0]();
  assert.equal(await waiting, false);
  assert.deepEqual(log, ["attempt", "failure:10", "attempt", "success:true"]);
});

test("a start while an attempt is still running is ignored", async () => {
  let release;
  let attempts = 0;
  const startup = createStartup({
    attempt: () => { attempts += 1; return new Promise((resolve) => { release = resolve; }); },
    wait: async () => {},
  });
  const first = startup.start();
  assert.equal(await startup.start(), false);
  release();
  assert.equal(await first, true);
  assert.equal(attempts, 1);
});
