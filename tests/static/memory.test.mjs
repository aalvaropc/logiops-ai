import { test } from "node:test";
import assert from "node:assert/strict";
import { moduleUrl, memoryStorage } from "./helpers.mjs";

const { createMemory, MEMORY_SESSION_KEY } = await import(moduleUrl("app/memory.js"));
const { createStorage } = await import(moduleUrl("app/api.js"));

function setup({ auth = { enabled: false }, session = null, token = "", request } = {}) {
  const backing = memoryStorage();
  const posts = [];
  const memory = createMemory({
    storage: createStorage(backing), fetch: async (url, init) => { posts.push({ url, init }); return { ok: true }; },
    request: request ?? (async (path) => ({ path, welcome: "Welcome back.", last_incident: "SHIP-433", turns: [] })),
    randomText: () => "abcdefghijkl", credentials: () => ({ auth, session, token }), incident: () => "SHIP-421",
  });
  return { memory, backing, posts };
}

test("one memory session per tab, created on first use", () => {
  const { memory, backing } = setup();
  assert.equal(memory.session(), "s-abcdefghijkl");
  assert.equal(backing.getItem(MEMORY_SESSION_KEY), "s-abcdefghijkl");
  backing.setItem(MEMORY_SESSION_KEY, "s-existing");
  assert.equal(memory.session(), "s-existing");
});

test("turns are remembered with the token and the incident, never for a guest", () => {
  const { memory, posts } = setup({ token: "tok" });
  assert.equal(memory.remember("user", "book it"), true);
  assert.equal(posts[0].url, "/memory/turns");
  assert.equal(posts[0].init.headers.Authorization, "Bearer tok");
  assert.deepEqual(JSON.parse(posts[0].init.body), { session: "s-abcdefghijkl", role: "user", text: "book it", incident: "SHIP-421" });
  assert.equal(JSON.parse(setup().posts.length ? "0" : "0"), 0);
  const guest = setup({ auth: { enabled: true }, session: null });
  assert.equal(guest.memory.remember("user", "hello"), false);
  assert.equal(guest.posts.length, 0);
  const signedIn = setup({ auth: { enabled: true }, session: { access: "a" } });
  assert.equal(signedIn.memory.remember("assistant", "x".repeat(5000)), true);
  assert.equal(JSON.parse(signedIn.posts[0].init.body).text.length, 4000);
});

test("recall asks for the previous session and swallows failures", async () => {
  const { memory } = setup();
  const recalled = await memory.recall();
  assert.equal(recalled.path, "/memory?session=s-abcdefghijkl");
  assert.equal(recalled.last_incident, "SHIP-433");
  const guest = setup({ auth: { enabled: true } });
  assert.equal(await guest.memory.recall(), null);
  const failing = setup({ request: async () => { throw new Error("502"); } });
  assert.equal(await failing.memory.recall(), null);
});
